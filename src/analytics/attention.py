"""Deterministic attention summary (Milestone 3, section G).

Aggregates the riskiest findings from the other analytics categories into a
single, evidence-backed list. This becomes the evidence source for a future
AI layer -- every record carries the numbers used to produce it.
"""

from datetime import date

from src.analytics.config import AnalyticsConfig

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _studio(issue_type: str, row: dict, severity: str, metric: str,
            observed_value, threshold, evidence: dict, explanation: str) -> dict:
    base = {
        "issue_type": issue_type,
        "severity": severity,
        "store_id": row.get("store_id"),
        "store_name": row.get("store_name"),
        "product_id": row.get("product_id"),
        "product_name": row.get("product_name"),
        "analysis_date": row.get("analysis_date"),
        "metric": metric,
        "observed_value": observed_value,
        "threshold": threshold,
        "evidence": evidence,
        "explanation": explanation,
        "data_status": row.get("data_status", "SUFFICIENT"),
    }
    return {k: v for k, v in base.items() if v is not None}


def build_attention(
    stockout_rows: list[dict],
    overstock_rows: list[dict],
    slow_rows: list[dict],
    anomaly_rows: list[dict],
    config: AnalyticsConfig,
    analysis_date: date,
) -> list[dict]:
    """Produce a severity-sorted attention list from every category."""
    items: list[dict] = []

    risk_map = {"CRITICAL": "CRITICAL", "HIGH": "HIGH"}
    for row in stockout_rows:
        severity = risk_map.get(row["status"])
        if not severity or row["data_status"] != "SUFFICIENT":
            continue
        items.append(
            _studio(
                "STOCK_OUT_RISK",
                row,
                severity,
                "days_of_stock",
                row.get("days_of_stock"),
                f"CRITICAL<=7 / HIGH<=14 / MEDIUM<=30 days",
                {
                    "current_stock": row.get("current_stock"),
                    "reorder_level": row.get("reorder_level"),
                    "average_daily_sales": row.get("average_daily_sales"),
                    "demand_window_days": (
                        row.get("evidence") or {}
                    ).get("demand_window_days"),
                    "below_reorder": row.get("below_reorder"),
                },
                row.get("explanation", ""),
            )
        )

    for row in overstock_rows:
        if row["status"] != "OVERSTOCK" or row["data_status"] != "SUFFICIENT":
            continue
        items.append(
            _studio(
                "OVERSTOCK",
                row,
                "MEDIUM",
                "stock_cover_days",
                row.get("stock_cover_days"),
                f">= {config.overstock_cover_days:g} days",
                {
                    "current_stock": row.get("current_stock"),
                    "average_daily_sales": row.get("average_daily_sales"),
                    "reorder_level": (row.get("evidence") or {}).get("reorder_level"),
                },
                row.get("explanation", ""),
            )
        )

    for row in slow_rows:
        if row["status"] != "SLOW_MOVER" or row["data_status"] != "SUFFICIENT":
            continue
        items.append(
            _studio(
                "SLOW_MOVER",
                row,
                "LOW",
                "average_daily_sales",
                row.get("average_daily_sales"),
                f"<= {config.slow_mover_daily_units:g} units/day",
                {
                    "units_sold": row.get("units_sold"),
                    "sales_days": row.get("sales_days"),
                    "period_start": row.get("period_start"),
                    "period_end": row.get("period_end"),
                },
                row.get("explanation", ""),
            )
        )

    for row in anomaly_rows:
        direction = row.get("direction")
        if direction == "SPIKE":
            items.append(
                _studio(
                    "SALES_SPIKE",
                    row,
                    "LOW",
                    "change_pct",
                    row.get("change_pct"),
                    f">= +{config.spike_threshold_pct:g}%",
                    {
                        "recent_units": row.get("recent_units"),
                        "baseline_units": row.get("baseline_units"),
                        **(row.get("evidence") or {}),
                    },
                    row.get("explanation", ""),
                )
            )
        elif direction == "DROP":
            items.append(
                _studio(
                    "SALES_DROP",
                    row,
                    "MEDIUM",
                    "change_pct",
                    row.get("change_pct"),
                    f"<= -{config.drop_threshold_pct:g}%",
                    {
                        "recent_units": row.get("recent_units"),
                        "baseline_units": row.get("baseline_units"),
                        **(row.get("evidence") or {}),
                    },
                    row.get("explanation", ""),
                )
            )

    items.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["issue_type"]))
    return items


def summarize(items: list[dict]) -> dict:
    """Counts per issue type for a compact dashboard summary."""
    counts = {
        "stock_out_risks": 0,
        "overstock": 0,
        "slow_movers": 0,
        "sales_spikes": 0,
        "sales_drops": 0,
        "total": len(items),
    }
    for item in items:
        key = {
            "STOCK_OUT_RISK": "stock_out_risks",
            "OVERSTOCK": "overstock",
            "SLOW_MOVER": "slow_movers",
            "SALES_SPIKE": "sales_spikes",
            "SALES_DROP": "sales_drops",
        }[item["issue_type"]]
        counts[key] += 1
    return counts