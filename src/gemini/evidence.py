"""Evidence pipeline for the grounded copilot (Milestone 4).

Deterministic analytics is the ONLY source of facts. This module routes an
intent to the relevant engine outputs, ranks/limits them, and converts them
into compact, serialisable evidence records. Gemini never receives raw
database rows -- it receives exactly what this module returns.
"""

from pathlib import Path
from typing import Optional

from src.analytics import engine as analytics_engine
from src.analytics.config import AnalyticsConfig, DEFAULT_CONFIG
from src.config import DATABASE_PATH

EVIDENCE_LIMIT = 8

SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _compact(record: dict) -> dict:
    """Strip nulls so evidence is concise and JSON-friendly."""
    return {key: value for key, value in record.items() if value is not None}


def _ranked_stockout(items: list[dict], reorder_first: bool = False) -> list[dict]:
    def sort_key(row: dict):
        below = 0 if row.get("below_reorder") else 1
        severity = SEVERITY_RANK.get(row.get("status"), 9)
        days = row.get("days_of_stock") if row.get("days_of_stock") is not None else 1e9
        return (below if reorder_first else severity, severity, days)

    return sorted(items, key=sort_key)


def _select(items: list[dict], limit: int) -> list[dict]:
    return items[:limit]


def build_evidence(
    intent: str,
    product_id: Optional[int] = None,
    store_id: Optional[int] = None,
    as_of_date=None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    db_path: Path = DATABASE_PATH,
    limit: int = EVIDENCE_LIMIT,
) -> dict:
    """Gather ranked evidence for the given intent from the analytics engine."""
    evidence: list[dict] = []

    if intent in ("stockout", "reorder"):
        result = analytics_engine.stockout_risks(
            db_path=db_path, store_id=store_id, product_id=product_id,
            as_of_date=as_of_date, config=config,
        )
        selected = _select(
            _ranked_stockout(result["items"], reorder_first=(intent == "reorder")), limit
        )
        for row in selected:
            evidence.append(
                _compact({
                    "type": "STOCK_OUT_RISK",
                    "category": "FACT" if row["data_status"] == "SUFFICIENT" else "INSUFFICIENT_DATA",
                    "severity": row.get("status"),
                    "store_id": row.get("store_id"),
                    "store_name": row.get("store_name"),
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name"),
                    "metric": "days_of_stock",
                    "value": row.get("days_of_stock"),
                    "threshold": "CRITICAL<=7 / HIGH<=14 / MEDIUM<=30 days",
                    "current_stock": row.get("current_stock"),
                    "reorder_level": row.get("reorder_level"),
                    "average_daily_sales": row.get("average_daily_sales"),
                    "estimated_stock_out_date": row.get("estimated_stock_out_date"),
                    "below_reorder": row.get("below_reorder"),
                    "analysis_date": row.get("analysis_date"),
                    "data_status": row.get("data_status"),
                })
            )

    elif intent == "overstock":
        result = analytics_engine.overstock(
            db_path=db_path, store_id=store_id, product_id=product_id,
            as_of_date=as_of_date, config=config,
        )
        overstocked = [r for r in result["items"] if r["status"] == "OVERSTOCK"]
        for row in _select(
            sorted(overstocked, key=lambda r: r["stock_cover_days"] or 0, reverse=True), limit
        ):
            evidence.append(
                _compact({
                    "type": "OVERSTOCK",
                    "category": "FACT",
                    "severity": "MEDIUM",
                    "store_id": row.get("store_id"),
                    "store_name": row.get("store_name"),
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name"),
                    "metric": "stock_cover_days",
                    "value": row.get("stock_cover_days"),
                    "threshold": f">= {config.overstock_cover_days:g} days",
                    "current_stock": row.get("current_stock"),
                    "average_daily_sales": row.get("average_daily_sales"),
                    "analysis_date": row.get("analysis_date"),
                    "data_status": row.get("data_status"),
                })
            )

    elif intent == "slow_movers":
        result = analytics_engine.slow_movers(
            db_path=db_path, store_id=store_id, product_id=product_id,
            as_of_date=as_of_date, config=config,
        )
        slow = [r for r in result["items"] if r["status"] == "SLOW_MOVER"]
        for row in _select(
            sorted(slow, key=lambda r: r["average_daily_sales"] or 0), limit
        ):
            evidence.append(
                _compact({
                    "type": "SLOW_MOVER",
                    "category": "FACT",
                    "severity": "LOW",
                    "store_id": row.get("store_id"),
                    "store_name": row.get("store_name"),
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name"),
                    "metric": "average_daily_sales",
                    "value": row.get("average_daily_sales"),
                    "threshold": f"<= {config.slow_mover_daily_units:g} units/day",
                    "units_sold": row.get("units_sold"),
                    "sales_days": row.get("sales_days"),
                    "analysis_date": row.get("analysis_date"),
                    "data_status": row.get("data_status"),
                })
            )

    elif intent == "forecast":
        result = analytics_engine.forecast(
            db_path=db_path, store_id=store_id, product_id=product_id,
            as_of_date=as_of_date, horizon_days=7, config=config,
        )
        forecastable = [
            r for r in result["items"]
            if r["forecast_status"] in ("SUFFICIENT_DATA", "LIMITED_DATA")
        ]
        if forecastable:
            counts = result["counts"]
            evidence.append(
                _compact({
                    "type": "FORECAST_SUMMARY",
                    "category": "FACT",
                    "metric": "counts",
                    "value": {
                        "total": counts["total"],
                        "rising_demand": counts["by_trend"].get("UP", 0),
                        "falling_demand": counts["by_trend"].get("DOWN", 0),
                        "inventory_at_risk": counts["by_inventory_outlook"].get("AT_RISK", 0),
                        "insufficient_data": counts["by_forecast_status"].get("INSUFFICIENT_DATA", 0),
                    },
                    "horizon_days": result["horizon_days"],
                    "analysis_date": result["analysis_date"],
                })
            )

            def forecast_rank(row):
                outlook = {"AT_RISK": 0, "WATCH": 1, "SUFFICIENT": 2}.get(
                    row.get("inventory_outlook"), 3
                )
                trend = {"UP": 0, "DOWN": 1, "STABLE": 2}.get(row.get("trend"), 3)
                return (outlook, trend, -(row.get("forecast_units") or 0))

            for row in _select(sorted(forecastable, key=forecast_rank), limit):
                evidence.append(
                    _compact({
                        "type": "FORECAST",
                        "category": "ESTIMATE",
                        "store_id": row.get("store_id"),
                        "store_name": row.get("store_name"),
                        "product_id": row.get("product_id"),
                        "product_name": row.get("product_name"),
                        "metric": "forecast_units",
                        "value": row.get("forecast_units"),
                        "forecast_status": row.get("forecast_status"),
                        "horizon_days": row.get("horizon_days"),
                        "recent_daily_demand": row.get("recent_daily_demand"),
                        "baseline_daily_demand": row.get("baseline_daily_demand"),
                        "trend": row.get("trend"),
                        "current_stock": row.get("current_stock"),
                        "inventory_outlook": row.get("inventory_outlook"),
                        "expected_cover_days": row.get("expected_cover_days"),
                        "analysis_date": row.get("analysis_date"),
                        "data_status": row.get("forecast_status"),
                    })
                )

    elif intent in ("spike", "drop", "anomaly"):
        result = analytics_engine.sales_anomalies(
            db_path=db_path, store_id=store_id, product_id=product_id,
            as_of_date=as_of_date, config=config,
        )
        direction = {"spike": "SPIKE", "drop": "DROP"}.get(intent)
        matches = [
            r for r in result["items"]
            if (direction and r["direction"] == direction) or (direction is None and r["direction"] in ("SPIKE", "DROP"))
        ]
        if direction == "spike":
            matches.sort(key=lambda r: r["change_pct"] or -1e9, reverse=True)
        elif direction == "drop":
            matches.sort(key=lambda r: r["change_pct"] or 1e9)
        else:
            matches.sort(
                key=lambda r: (-(r["change_pct"] or 0) if r["direction"] == "SPIKE" else (r["change_pct"] or 0))
            )
        for row in _select(matches, limit):
            evidence.append(
                _compact({
                    "type": "SALES_" + row["direction"],
                    "category": "FACT",
                    "severity": "LOW" if row["direction"] == "SPIKE" else "MEDIUM",
                    "store_id": row.get("store_id"),
                    "store_name": row.get("store_name"),
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name"),
                    "metric": "change_pct",
                    "value": row.get("change_pct"),
                    "threshold": (
                        f">= +{config.spike_threshold_pct:g}%" if row["direction"] == "SPIKE"
                        else f"<= -{config.drop_threshold_pct:g}%"
                    ),
                    "recent_units": row.get("recent_units"),
                    "baseline_units": row.get("baseline_units"),
                    "recent_window_start": (row.get("evidence") or {}).get("recent_window_start"),
                    "recent_window_end": (row.get("evidence") or {}).get("recent_window_end"),
                    "baseline_window_start": (row.get("evidence") or {}).get("baseline_window_start"),
                    "baseline_window_end": (row.get("evidence") or {}).get("baseline_window_end"),
                    "analysis_date": row.get("analysis_date"),
                    "data_status": row.get("data_status"),
                })
            )

    elif intent == "product_performance":
        result = analytics_engine.product_performance(
            db_path=db_path, product_id=product_id,
            as_of_date=as_of_date, config=config,
        )
        items = list(result["items"])
        if product_id is None:
            items.sort(key=lambda r: r["units_sold"], reverse=True)
        for row in _select(items, limit):
            evidence.append(
                _compact({
                    "type": "PRODUCT_PERFORMANCE",
                    "category": "FACT",
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name"),
                    "category": row.get("category"),
                    "metric": "units_sold",
                    "value": row.get("units_sold"),
                    "revenue": row.get("revenue"),
                    "average_daily_units": row.get("average_daily_units"),
                    "change_units_pct": row.get("change_units_pct"),
                    "trend": row.get("trend"),
                    "period_start": row.get("period_start"),
                    "period_end": row.get("period_end"),
                    "analysis_date": row.get("analysis_date"),
                })
            )

    elif intent == "store_performance":
        result = analytics_engine.store_performance(
            db_path=db_path, store_id=store_id,
            as_of_date=as_of_date, config=config,
        )
        items = list(result["items"])
        if store_id is None:
            items.sort(key=lambda r: r["revenue"] or 0, reverse=True)
        for row in _select(items, limit):
            evidence.append(
                _compact({
                    "type": "STORE_PERFORMANCE",
                    "category": "FACT",
                    "store_id": row.get("store_id"),
                    "store_name": row.get("store_name"),
                    "metric": "revenue",
                    "value": row.get("revenue"),
                    "units_sold": row.get("units_sold"),
                    "average_daily_units": row.get("average_daily_units"),
                    "change_units_pct": row.get("change_units_pct"),
                    "trend": row.get("trend"),
                    "period_start": row.get("period_start"),
                    "period_end": row.get("period_end"),
                    "analysis_date": row.get("analysis_date"),
                })
            )

    elif intent == "attention":
        result = analytics_engine.attention_summary(
            db_path=db_path, store_id=store_id, product_id=product_id,
            as_of_date=as_of_date, config=config,
        )
        counts = result["counts"]
        evidence.append(
            _compact({
                "type": "ATTENTION_SUMMARY",
                "category": "FACT",
                "metric": "counts",
                "value": counts,
                "analysis_date": result.get("analysis_date"),
            })
        )
        for row in _select(result["items"], limit):
            evidence.append(
                _compact({
                    "type": row.get("issue_type"),
                    "category": "FACT",
                    "severity": row.get("severity"),
                    "store_id": row.get("store_id"),
                    "store_name": row.get("store_name"),
                    "product_id": row.get("product_id"),
                    "product_name": row.get("product_name"),
                    "metric": row.get("metric"),
                    "value": row.get("observed_value"),
                    "threshold": row.get("threshold"),
                    "evidence": row.get("evidence"),
                    "analysis_date": row.get("analysis_date"),
                    "data_status": row.get("data_status"),
                })
            )

    analysis_date = next(
        (item["analysis_date"] for item in evidence if item.get("analysis_date")),
        None,
    )
    if analysis_date is None:
        from src.analytics.data import resolve_analysis_date
        analysis_date = resolve_analysis_date(as_of_date, db_path).isoformat()

    data_status = "SUFFICIENT" if evidence else "INSUFFICIENT_DATA"
    return {
        "evidence": evidence,
        "analysis_date": analysis_date,
        "data_status": data_status,
        "intent": intent,
    }