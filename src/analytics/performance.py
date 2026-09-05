"""Product and store performance analytics (Milestone 3, sections A and F).

Measurement only: units, revenue, averages, period-over-period change, and a
trend direction. Nothing is labelled "good" or "bad" -- the raw numbers are
reported so a later AI layer can draw its own grounded conclusions.
"""

from datetime import date, timedelta
from typing import Callable

from src.analytics.config import AnalyticsConfig
from src.analytics.metrics import average_daily, days_between, pct_change, round2, trend_direction


def aggregate_series(
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    match: Callable[[int, int], bool],
) -> dict[date, dict]:
    """Sum the daily series of every (store, product) satisfying `match`.

    Returns a single day->{"units", "revenue"} series.
    """
    combined: dict[date, dict] = {}
    for (sid, spid), series in sales_by_day.items():
        if not match(sid, spid):
            continue
        for day, row in series.items():
            entry = combined.setdefault(day, {"units": 0, "revenue": 0.0})
            entry["units"] += float(row["units"])
            entry["revenue"] += float(row["revenue"])
    return combined


def _halves(start: date, end: date) -> tuple[tuple[date, date], tuple[date, date]]:
    """Split [start, end] into two contiguous halves."""
    total = days_between(start, end)
    first_len = (total + 1) // 2
    split = start + timedelta(days=first_len - 1)
    return (start, split), (split + timedelta(days=1), end)


def _range_totals(series: dict[date, dict], start: date, end: date) -> dict:
    units = 0.0
    revenue = 0.0
    for day, row in series.items():
        if start <= day <= end:
            units += float(row["units"])
            revenue += float(row["revenue"])
    return {"units": units, "revenue": round2(revenue), "days": days_between(start, end)}


def _trend_in_period(
    series: dict[date, dict], start: date, end: date, config: AnalyticsConfig
) -> dict:
    if days_between(start, end) < 8:
        return {"trend": "UNKNOWN", "trend_evidence": {}}
    (fh_start, fh_end), (sh_start, sh_end) = _halves(start, end)
    first = _range_totals(series, fh_start, fh_end)
    second = _range_totals(series, sh_start, sh_end)
    first_avg = average_daily(first["units"], first["days"])
    second_avg = average_daily(second["units"], second["days"])
    return {
        "trend": trend_direction(first_avg, second_avg, config.trend_change_threshold_pct),
        "trend_evidence": {
            "first_half_average_daily_units": round2(first_avg),
            "second_half_average_daily_units": round2(second_avg),
        },
    }


def build_performance_item(
    series: dict[date, dict],
    period_start: date,
    period_end: date,
    config: AnalyticsConfig,
    analysis_date: date,
    identity: dict,
) -> dict:
    period_days = days_between(period_start, period_end)
    prev_end = period_start - timedelta(days=1)
    prev_start = period_start - timedelta(days=period_days)

    current = _range_totals(series, period_start, period_end)
    previous = _range_totals(series, prev_start, prev_end)
    trend = _trend_in_period(series, period_start, period_end, config)

    return {
        **identity,
        "analysis_date": analysis_date.isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "previous_period_start": prev_start.isoformat(),
        "previous_period_end": prev_end.isoformat(),
        "period_days": period_days,
        "units_sold": int(current["units"]),
        "revenue": current["revenue"],
        "average_daily_units": round2(current["units"] / period_days) if period_days else 0.0,
        "average_daily_revenue": round2(current["revenue"] / period_days) if period_days else 0.0,
        "previous_units_sold": int(previous["units"]),
        "previous_revenue": previous["revenue"],
        "change_units_pct": pct_change(current["units"], previous["units"]),
        "change_revenue_pct": pct_change(current["revenue"], previous["revenue"]),
        "trend": trend["trend"],
        "trend_evidence": trend["trend_evidence"],
        "data_status": "SUFFICIENT" if period_days >= 1 else "INSUFFICIENT_DATA",
    }


def product_performance(
    products: dict[int, dict],
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    period_start: date,
    period_end: date,
    config: AnalyticsConfig,
    analysis_date: date,
    product_id: int | None = None,
) -> list[dict]:
    """Per-product performance over the analysis period (chain-wide)."""
    items = []
    for pid in sorted(products):
        if product_id is not None and pid != product_id:
            continue
        product = products[pid]
        series = aggregate_series(sales_by_day, lambda sid, spid: spid == pid)
        items.append(
            build_performance_item(
                series,
                period_start,
                period_end,
                config,
                analysis_date,
                {
                    "product_id": pid,
                    "product_name": product["product_name"],
                    "category": product["category"],
                    "unit_price": product["unit_price"],
                },
            )
        )
    return items


def store_performance(
    stores: dict[int, dict],
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    period_start: date,
    period_end: date,
    config: AnalyticsConfig,
    analysis_date: date,
    store_id: int | None = None,
) -> list[dict]:
    """Per-store performance over the analysis period."""
    items = []
    for sid in sorted(stores):
        if store_id is not None and sid != store_id:
            continue
        store = stores[sid]
        series = aggregate_series(sales_by_day, lambda sid_, spid: sid_ == sid)
        items.append(
            build_performance_item(
                series,
                period_start,
                period_end,
                config,
                analysis_date,
                {"store_id": sid, "store_name": store["store_name"]},
            )
        )
    return items