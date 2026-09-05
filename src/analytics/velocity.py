"""Slow-moving inventory detection (Milestone 3, section D).

A store/product is labelled SLOW_MOVER when, within the demand window, its
average daily sales are below the configured threshold AND it demonstrably
sold on enough distinct days to have a reliable measurement. Products with
very little history are reported as INSUFFICIENT_DATA rather than guessed at.
"""

from datetime import date

from src.analytics.config import AnalyticsConfig
from src.analytics.metrics import demand_stats, round2


def slow_movers(
    inventory: list[dict],
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    demand_start: date,
    demand_end: date,
    config: AnalyticsConfig,
    analysis_date: date,
) -> list[dict]:
    """Slow-mover assessment for every store/product inventory record."""
    rows = []
    for inv in inventory:
        sid, pid = inv["store_id"], inv["product_id"]
        series = sales_by_day.get((sid, pid), {})
        stats = demand_stats(series, demand_start, demand_end, config.min_history_days)

        if stats["data_status"] == "INSUFFICIENT_DATA":
            rows.append(
                {
                    "store_id": sid,
                    "store_name": inv["store_name"],
                    "product_id": pid,
                    "product_name": inv["product_name"],
                    "analysis_date": analysis_date.isoformat(),
                    "period_start": demand_start.isoformat(),
                    "period_end": demand_end.isoformat(),
                    "units_sold": 0,
                    "average_daily_sales": None,
                    "sales_days": 0,
                    "threshold_daily_units": config.slow_mover_daily_units,
                    "min_sales_days": config.slow_mover_min_sales_days,
                    "status": "INSUFFICIENT_DATA",
                    "data_status": "INSUFFICIENT_DATA",
                    "evidence": {
                        "demand_window_days": stats["window_days"],
                        "units_sold_window": int(stats["units_sold"]),
                        "sales_days": stats["sales_days"],
                    },
                    "explanation": (
                        "Insufficient sales history to classify this product reliably."
                    ),
                }
            )
            continue

        avg = stats["average_daily_sales"]
        sales_days = stats["sales_days"]
        is_slow = avg <= config.slow_mover_daily_units and sales_days >= config.slow_mover_min_sales_days
        if avg <= 0 and sales_days == 0:
            status = "INSUFFICIENT_DATA"
            explanation = (
                "No sales observed in the demand window; cannot classify as slow mover."
            )
        else:
            status = "SLOW_MOVER" if is_slow else "NORMAL"
            explanation = (
                f"Average daily sales of {round2(avg)} units/day vs slow-mover threshold of "
                f"{config.slow_mover_daily_units:g} units/day over {sales_days} selling days."
            )

        rows.append(
            {
                "store_id": sid,
                "store_name": inv["store_name"],
                "product_id": pid,
                "product_name": inv["product_name"],
                "analysis_date": analysis_date.isoformat(),
                "period_start": demand_start.isoformat(),
                "period_end": demand_end.isoformat(),
                "units_sold": int(stats["units_sold"]),
                "average_daily_sales": round2(avg),
                "sales_days": sales_days,
                "threshold_daily_units": config.slow_mover_daily_units,
                "min_sales_days": config.slow_mover_min_sales_days,
                "status": status,
                "data_status": stats["data_status"],
                "evidence": {
                    "demand_window_days": stats["window_days"],
                    "units_sold_window": int(stats["units_sold"]),
                    "sales_days": sales_days,
                },
                "explanation": explanation,
            }
        )
    return rows