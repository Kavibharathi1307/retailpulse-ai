"""Inventory-based analytics: stock-out risk and overstock (Milestone 3, B and C).

Documented formulas:

    average_daily_sales = total units in demand window / demand window days
    days_of_stock       = current_stock / average_daily_sales
    stock_cover_days    = current_stock / average_daily_sales

These are ESTIMATES based on observed historical demand -- never guarantees of
future events. When there is no recent sales activity the status is UNKNOWN /
INSUFFICIENT_DATA and no date is invented.
"""

from datetime import date, timedelta

from src.analytics.config import AnalyticsConfig
from src.analytics.metrics import (
    ceiling,
    demand_stats,
    days_between,
    round1,
    round2,
    window_end,
)


def _risk_status(days_of_stock: float, config: AnalyticsConfig) -> str:
    if days_of_stock <= config.stockout_critical_days:
        return "CRITICAL"
    if days_of_stock <= config.stockout_high_days:
        return "HIGH"
    if days_of_stock <= config.stockout_medium_days:
        return "MEDIUM"
    return "LOW"


def stockout_risks(
    inventory: list[dict],
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    demand_start: date,
    demand_end: date,
    config: AnalyticsConfig,
    analysis_date: date,
) -> list[dict]:
    """Stock-out risk for every store/product inventory record."""
    rows = []
    for inv in inventory:
        sid, pid = inv["store_id"], inv["product_id"]
        series = sales_by_day.get((sid, pid), {})
        stats = demand_stats(series, demand_start, demand_end, config.min_history_days)
        current_stock = float(inv["current_stock"])
        avg = stats["average_daily_sales"]
        below_reorder = current_stock < float(inv["reorder_level"])

        if stats["data_status"] == "INSUFFICIENT_DATA":
            rows.append(
                {
                    "store_id": sid,
                    "store_name": inv["store_name"],
                    "product_id": pid,
                    "product_name": inv["product_name"],
                    "analysis_date": analysis_date.isoformat(),
                    "current_stock": int(current_stock),
                    "reorder_level": int(inv["reorder_level"]),
                    "average_daily_sales": None,
                    "days_of_stock": None,
                    "estimated_stock_out_date": None,
                    "status": "UNKNOWN",
                    "below_reorder": below_reorder,
                    "data_status": "INSUFFICIENT_DATA",
                    "evidence": {
                        "demand_window_start": demand_start.isoformat(),
                        "demand_window_end": demand_end.isoformat(),
                        "demand_window_days": stats["window_days"],
                        "units_sold_window": int(stats["units_sold"]),
                        "sales_days": stats["sales_days"],
                    },
                    "explanation": (
                        "Not enough sales history in the demand window to estimate "
                        "a reliable average daily sales rate."
                    ),
                }
            )
            continue

        if avg <= 0 or days_between(demand_start, demand_end) < config.min_history_days:
            rows.append(
                {
                    "store_id": sid,
                    "store_name": inv["store_name"],
                    "product_id": pid,
                    "product_name": inv["product_name"],
                    "analysis_date": analysis_date.isoformat(),
                    "current_stock": int(current_stock),
                    "reorder_level": int(inv["reorder_level"]),
                    "average_daily_sales": 0.0,
                    "days_of_stock": None,
                    "estimated_stock_out_date": None,
                    "status": "UNKNOWN",
                    "below_reorder": below_reorder,
                    "data_status": "INSUFFICIENT_DATA",
                    "evidence": {
                        "demand_window_start": demand_start.isoformat(),
                        "demand_window_end": demand_end.isoformat(),
                        "demand_window_days": stats["window_days"],
                        "units_sold_window": int(stats["units_sold"]),
                        "sales_days": stats["sales_days"],
                    },
                    "explanation": (
                        "No recent sales were observed for this product, so a "
                        "stock-out date cannot be estimated."
                    ),
                }
            )
            continue

        days_of_stock = round1(current_stock / avg)
        stock_out_date = analysis_date + timedelta(days=ceiling(days_of_stock))
        rows.append(
            {
                "store_id": sid,
                "store_name": inv["store_name"],
                "product_id": pid,
                "product_name": inv["product_name"],
                "analysis_date": analysis_date.isoformat(),
                "current_stock": int(current_stock),
                "reorder_level": int(inv["reorder_level"]),
                "average_daily_sales": round2(avg),
                "days_of_stock": days_of_stock,
                "estimated_stock_out_date": stock_out_date.isoformat(),
                "status": _risk_status(days_of_stock, config),
                "below_reorder": below_reorder,
                "data_status": "SUFFICIENT",
                "evidence": {
                    "demand_window_start": demand_start.isoformat(),
                    "demand_window_end": demand_end.isoformat(),
                    "demand_window_days": stats["window_days"],
                    "units_sold_window": int(stats["units_sold"]),
                    "sales_days": stats["sales_days"],
                },
                "explanation": (
                    f"Estimated {days_of_stock} days of stock remaining at an average of "
                    f"{round2(avg)} units/day; reorder level is {int(inv['reorder_level'])}."
                ),
            }
        )
    return rows


def overstock(
    inventory: list[dict],
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    demand_start: date,
    demand_end: date,
    config: AnalyticsConfig,
    analysis_date: date,
) -> list[dict]:
    """Overstock detection from stock cover relative to observed demand."""
    rows = []
    for inv in inventory:
        sid, pid = inv["store_id"], inv["product_id"]
        series = sales_by_day.get((sid, pid), {})
        stats = demand_stats(series, demand_start, demand_end, config.min_history_days)
        current_stock = float(inv["current_stock"])

        if stats["data_status"] == "INSUFFICIENT_DATA":
            rows.append(
                {
                    "store_id": sid,
                    "store_name": inv["store_name"],
                    "product_id": pid,
                    "product_name": inv["product_name"],
                    "analysis_date": analysis_date.isoformat(),
                    "current_stock": int(current_stock),
                    "average_daily_sales": None,
                    "stock_cover_days": None,
                    "threshold_days": config.overstock_cover_days,
                    "status": "NORMAL",
                    "data_status": "INSUFFICIENT_DATA",
                    "evidence": {
                        "demand_window_start": demand_start.isoformat(),
                        "demand_window_end": demand_end.isoformat(),
                        "demand_window_days": stats["window_days"],
                        "units_sold_window": int(stats["units_sold"]),
                        "sales_days": stats["sales_days"],
                        "reorder_level": int(inv["reorder_level"]),
                    },
                    "explanation": (
                        "Insufficient sales history to evaluate stock cover."
                    ),
                }
            )
            continue

        avg = stats["average_daily_sales"]
        if avg <= 0:
            rows.append(
                {
                    "store_id": sid,
                    "store_name": inv["store_name"],
                    "product_id": pid,
                    "product_name": inv["product_name"],
                    "analysis_date": analysis_date.isoformat(),
                    "current_stock": int(current_stock),
                    "average_daily_sales": 0.0,
                    "stock_cover_days": None,
                    "threshold_days": config.overstock_cover_days,
                    "status": "NORMAL",
                    "data_status": "INSUFFICIENT_DATA",
                    "evidence": {
                        "demand_window_start": demand_start.isoformat(),
                        "demand_window_end": demand_end.isoformat(),
                        "demand_window_days": stats["window_days"],
                        "units_sold_window": int(stats["units_sold"]),
                        "sales_days": stats["sales_days"],
                        "reorder_level": int(inv["reorder_level"]),
                    },
                    "explanation": (
                        "No recent sales observed; stock cover cannot be evaluated."
                    ),
                }
            )
            continue

        cover = round1(current_stock / avg)
        status = "OVERSTOCK" if cover >= config.overstock_cover_days else "NORMAL"
        rows.append(
            {
                "store_id": sid,
                "store_name": inv["store_name"],
                "product_id": pid,
                "product_name": inv["product_name"],
                "analysis_date": analysis_date.isoformat(),
                "current_stock": int(current_stock),
                "average_daily_sales": round2(avg),
                "stock_cover_days": cover,
                "threshold_days": config.overstock_cover_days,
                "status": status,
                "data_status": "SUFFICIENT",
                "evidence": {
                    "demand_window_start": demand_start.isoformat(),
                    "demand_window_end": demand_end.isoformat(),
                    "demand_window_days": stats["window_days"],
                    "units_sold_window": int(stats["units_sold"]),
                    "sales_days": stats["sales_days"],
                    "reorder_level": int(inv["reorder_level"]),
                },
                "explanation": (
                    f"Stock cover is {cover} days (threshold {config.overstock_cover_days:g} "
                    f"days) based on average daily sales of {round2(avg)} units/day."
                ),
            }
        )
    return rows