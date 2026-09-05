"""Deterministic decision engine for actionable retail recommendations (M6).

Layer 1 of the two-layer architecture. Every recommendation is derived from the
analytics engine's outputs (stock-out risk, overstock, slow movers, anomalies)
using documented thresholds. Nothing is invented:

* the recommended action category is chosen by a deterministic rule;
* priority is assigned by a transparent scoring table;
* when evidence is insufficient, INSUFFICIENT_DATA is returned with the reason,
  never a fabricated recommendation.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from src.analytics import data, engine
from src.analytics.config import AnalyticsConfig, DEFAULT_CONFIG

# Priority ordering used to sort recommendations (most urgent first).
PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# - Priority scoring (documented, transparent) -----------------------------
# Each recommendation inherits its priority directly from a deterministic
# rule tied to the analytics engine thresholds -- there are no arbitrary
# point scores. The mapping is:
#
#   CRITICAL: immediate stock-out risk (stock cover <= 7 days)
#             OR the engine flagged the item CRITICAL.
#   HIGH:     high stock-out risk (cover <= 14 days)
#             OR significant overstock (cover >= 2x 60-day threshold)
#             OR severe sales drop (change <= -100%) or spike (change >= +200%).
#   MEDIUM:   slow mover, moderate overstock, moderate anomaly.
#   LOW:      low-priority or insufficient-data scrutinee.
#
# Every priority is derived from a measured value compared against a
# documented threshold, so it can always be explained from the evidence.


def _stockout_threshold(severity: str, config: AnalyticsConfig) -> float:
    """Return the applicable days-of-stock threshold for a risk severity."""
    if severity == "CRITICAL":
        return config.stockout_critical_days
    if severity == "HIGH":
        return config.stockout_high_days
    return config.stockout_medium_days


def _stockout_recommendation(row: dict, config: AnalyticsConfig) -> dict:
    """Build a REPLENISH recommendation from a stock-out risk row.

    CRITICAL/HIGH rows with sufficient demand become high-priority
    replenishment actions. Rows the engine could not measure (UNKNOWN /
    INSUFFICIENT_DATA, e.g. zero demand or too little history) still surface a
    REPLENISH review with an explicit reason and LOW priority -- never an
    invented quantity or date.
    """
    severity = row.get("status")
    if severity == "UNKNOWN":
        current_stock = row.get("current_stock")
        return {
            "priority": "LOW",
            "type": "REPLENISH",
            "store_id": row.get("store_id"),
            "store_name": row.get("store_name"),
            "product_id": row.get("product_id"),
            "product_name": row.get("product_name"),
            "analysis_date": row.get("analysis_date"),
            "reason": "Insufficient demand history for a reliable replenishment estimate.",
            "evidence": {
                "current_stock": current_stock,
                "average_daily_demand": None,
                "stock_cover_days": None,
                "threshold_days": config.stockout_medium_days,
            },
            "action": "Prioritize replenishment review.",
            "data_status": "INSUFFICIENT_DATA",
        }
    if severity not in ("CRITICAL", "HIGH"):
        return None

    store_id = row.get("store_id")
    store_name = row.get("store_name")
    product_id = row.get("product_id")
    product_name = row.get("product_name")
    analysis_date = row.get("analysis_date")
    current_stock = row.get("current_stock")
    avg_daily = row.get("average_daily_sales")
    days = row.get("days_of_stock")
    data_status = row.get("data_status")

    if data_status != "SUFFICIENT" or avg_daily is None or days is None or avg_daily <= 0:
        reason = "Insufficient demand history for a reliable replenishment estimate."
        return {
            "priority": "LOW",
            "type": "REPLENISH",
            "store_id": store_id,
            "store_name": store_name,
            "product_id": product_id,
            "product_name": product_name,
            "analysis_date": analysis_date,
            "reason": reason,
            "evidence": {
                "current_stock": current_stock,
                "average_daily_demand": avg_daily,
                "stock_cover_days": None,
                "threshold_days": _stockout_threshold(severity, config),
            },
            "action": "Prioritize replenishment review.",
            "data_status": "INSUFFICIENT_DATA",
        }

    threshold = _stockout_threshold(severity, config)
    return {
        "priority": severity,
        "type": "REPLENISH",
        "store_id": store_id,
        "store_name": store_name,
        "product_id": product_id,
        "product_name": product_name,
        "analysis_date": analysis_date,
        "reason": (
            f"Stock cover of {days} days is below the configured "
            f"{threshold:g} day threshold; current stock is {current_stock} units "
            f"against an average daily demand of {avg_daily} units/day."
        ),
        "evidence": {
            "current_stock": current_stock,
            "average_daily_demand": avg_daily,
            "stock_cover_days": days,
            "threshold_days": threshold,
        },
        "action": "Prioritize replenishment.",
        "data_status": "SUFFICIENT",
    }


def _overstock_recommendation(row: dict, config: AnalyticsConfig) -> dict:
    """Build a REDUCE_INVENTORY recommendation from an overstock row."""
    if row.get("status") != "OVERSTOCK" or row.get("data_status") != "SUFFICIENT":
        return None
    cover = row.get("stock_cover_days")
    if cover is None:
        return None
    severity = "HIGH" if cover >= config.overstock_cover_days * 2 else "MEDIUM"
    return {
        "priority": severity,
        "type": "REDUCE_INVENTORY",
        "store_id": row.get("store_id"),
        "store_name": row.get("store_name"),
        "product_id": row.get("product_id"),
        "product_name": row.get("product_name"),
        "analysis_date": row.get("analysis_date"),
        "reason": (
            f"Stock cover of {cover} days exceeds the "
            f"{config.overstock_cover_days:g} day overstock threshold."
        ),
        "evidence": {
            "current_stock": row.get("current_stock"),
            "average_daily_demand": row.get("average_daily_sales"),
            "stock_cover_days": cover,
            "threshold_days": config.overstock_cover_days,
        },
        "action": "Review replenishment frequency and consider reducing incoming stock.",
        "data_status": "SUFFICIENT",
    }


def _slow_mover_recommendation(row: dict, config: AnalyticsConfig) -> dict:
    """Build a REVIEW_SLOW_MOVER recommendation from a slow-mover row."""
    if row.get("status") != "SLOW_MOVER" or row.get("data_status") != "SUFFICIENT":
        return None
    units_sold = row.get("units_sold")
    sales_days = row.get("sales_days")
    avg_daily = row.get("average_daily_sales")
    return {
        "priority": "MEDIUM",
        "type": "REVIEW_SLOW_MOVER",
        "store_id": row.get("store_id"),
        "store_name": row.get("store_name"),
        "product_id": row.get("product_id"),
        "product_name": row.get("product_name"),
        "analysis_date": row.get("analysis_date"),
        "reason": (
            f"Low demonstrated demand: {avg_daily} units/day ({units_sold} units "
            f"over {sales_days} selling days), below the "
            f"{config.slow_mover_daily_units:g} units/day slow-mover threshold."
        ),
        "evidence": {
            "average_daily_sales": avg_daily,
            "selling_days": sales_days,
            "units_sold": units_sold,
            "threshold_daily_units": config.slow_mover_daily_units,
            "min_selling_days": config.slow_mover_min_sales_days,
        },
        "action": "Review this product's sales performance before the next replenishment cycle.",
        "data_status": "SUFFICIENT",
    }


def _sales_drop_recommendation(row: dict, config: AnalyticsConfig) -> dict:
    """Build an INVESTIGATE_SALES_DROP recommendation from an anomaly row."""
    if row.get("direction") != "DROP":
        return None
    change = row.get("change_pct")
    if change is None:
        return None
    severity = "HIGH" if change <= -config.drop_threshold_pct * 2 else "MEDIUM"
    return {
        "priority": severity,
        "type": "INVESTIGATE_SALES_DROP",
        "store_id": row.get("store_id"),
        "store_name": row.get("store_name"),
        "product_id": row.get("product_id"),
        "product_name": row.get("product_name"),
        "analysis_date": row.get("analysis_date"),
        "reason": (
            f"Recent sales rate is {change}% below the baseline rate, exceeding "
            f"the {config.drop_threshold_pct:g}% drop threshold."
        ),
        "evidence": {
            "recent_daily_rate": (row.get("evidence") or {}).get("recent_daily_rate"),
            "baseline_daily_rate": (row.get("evidence") or {}).get("baseline_daily_rate"),
            "change_pct": change,
            "recent_units": row.get("recent_units"),
            "baseline_units": row.get("baseline_units"),
            "recent_window_start": (row.get("evidence") or {}).get("recent_window_start"),
            "recent_window_end": (row.get("evidence") or {}).get("recent_window_end"),
            "baseline_window_start": (row.get("evidence") or {}).get("baseline_window_start"),
            "baseline_window_end": (row.get("evidence") or {}).get("baseline_window_end"),
        },
        "action": (
            "Investigate the sales decline and check whether inventory availability "
            "or demand conditions explain the drop."
        ),
        "data_status": "SUFFICIENT",
    }


def _sales_spike_recommendation(row: dict, config: AnalyticsConfig) -> dict:
    """Build a MONITOR_DEMAND recommendation from an anomaly spike row."""
    if row.get("direction") != "SPIKE":
        return None
    change = row.get("change_pct")
    if change is None:
        return None
    severity = "HIGH" if change >= config.spike_threshold_pct * 2 else "MEDIUM"
    return {
        "priority": severity,
        "type": "MONITOR_DEMAND",
        "store_id": row.get("store_id"),
        "store_name": row.get("store_name"),
        "product_id": row.get("product_id"),
        "product_name": row.get("product_name"),
        "analysis_date": row.get("analysis_date"),
        "reason": (
            f"Recent sales rate is {change}% above the baseline rate, exceeding "
            f"the {config.spike_threshold_pct:g}% spike threshold."
        ),
        "evidence": {
            "recent_daily_rate": (row.get("evidence") or {}).get("recent_daily_rate"),
            "baseline_daily_rate": (row.get("evidence") or {}).get("baseline_daily_rate"),
            "change_pct": change,
            "recent_units": row.get("recent_units"),
            "baseline_units": row.get("baseline_units"),
            "recent_window_start": (row.get("evidence") or {}).get("recent_window_start"),
            "recent_window_end": (row.get("evidence") or {}).get("recent_window_end"),
            "baseline_window_start": (row.get("evidence") or {}).get("baseline_window_start"),
            "baseline_window_end": (row.get("evidence") or {}).get("baseline_window_end"),
        },
        "action": (
            "Monitor demand and inventory availability to avoid a potential "
            "stock-out if the elevated demand continues."
        ),
        "data_status": "SUFFICIENT",
    }


def build_recommendations(
    stockout_rows: list[dict],
    overstock_rows: list[dict],
    slow_rows: list[dict],
    anomaly_rows: list[dict],
    config: AnalyticsConfig,
    analysis_date: date,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
) -> list[dict]:
    """Produce the complete deterministic recommendation list.

    Each engine row is converted independently; recommendations are then
    sorted by priority (CRITICAL first) then by type, so the caller sees the
    most urgent items first without any arbitrary scoring.
    """
    recs: list[dict] = []

    for row in stockout_rows:
        if store_id is not None and row.get("store_id") != store_id:
            continue
        if product_id is not None and row.get("product_id") != product_id:
            continue
        rec = _stockout_recommendation(row, config)
        if rec:
            recs.append(rec)

    for row in overstock_rows:
        if store_id is not None and row.get("store_id") != store_id:
            continue
        if product_id is not None and row.get("product_id") != product_id:
            continue
        rec = _overstock_recommendation(row, config)
        if rec:
            recs.append(rec)

    for row in slow_rows:
        if store_id is not None and row.get("store_id") != store_id:
            continue
        if product_id is not None and row.get("product_id") != product_id:
            continue
        rec = _slow_mover_recommendation(row, config)
        if rec:
            recs.append(rec)

    for row in anomaly_rows:
        if store_id is not None and row.get("store_id") != store_id:
            continue
        if product_id is not None and row.get("product_id") != product_id:
            continue
        rec = _sales_drop_recommendation(row, config) or _sales_spike_recommendation(row, config)
        if rec:
            recs.append(rec)

    recs.sort(
        key=lambda r: (PRIORITY_ORDER.get(r["priority"], 9), r["type"], r["store_id"] or 0, r["product_id"] or 0)
    )
    return recs


def recommendations(
    db_path: Path = data.DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    """Full deterministic recommendation pipeline fed by the analytics engine."""
    analysis_date = data.resolve_analysis_date(as_of_date, db_path)

    stock_rows = engine.stockout_risks(
        db_path=db_path, store_id=store_id, product_id=product_id,
        as_of_date=analysis_date, config=config,
    )["items"]
    overs_rows = engine.overstock(
        db_path=db_path, store_id=store_id, product_id=product_id,
        as_of_date=analysis_date, config=config,
    )["items"]
    slow_rows = engine.slow_movers(
        db_path=db_path, store_id=store_id, product_id=product_id,
        as_of_date=analysis_date, config=config,
    )["items"]
    anomaly_rows = engine.sales_anomalies(
        db_path=db_path, store_id=store_id, product_id=product_id,
        as_of_date=analysis_date, config=config,
    )["items"]

    items = build_recommendations(
        stock_rows, overs_rows, slow_rows, anomaly_rows,
        config, analysis_date, store_id, product_id,
    )
    priority_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    type_counts = {}
    for rec in items:
        priority_counts[rec["priority"]] = priority_counts.get(rec["priority"], 0) + 1
        type_counts[rec["type"]] = type_counts.get(rec["type"], 0) + 1

    return {
        "analysis_date": analysis_date.isoformat(),
        "counts": {
            "priority": priority_counts,
            "type": type_counts,
            "total": len(items),
        },
        "items": items,
    }
