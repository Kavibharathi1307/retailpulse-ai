"""Shared deterministic helpers for the analytics engine.

These functions are pure (no I/O) and implement the small numeric rules reused
across every analytics category.
"""

import math
from datetime import date, timedelta


def round2(value: float) -> float:
    """Round to 2 decimal places without float noise."""
    return round(float(value), 2)


def round1(value: float) -> float:
    """Round to 1 decimal place."""
    return round(float(value), 1)


def pct_change(current: float, previous: float) -> float | None:
    """Percentage change; returns None when the previous value is zero/absent."""
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def average_daily(total: float, days: int) -> float:
    """Average per day over the given number of days (safe against zero)."""
    if days <= 0:
        return 0.0
    return round2(total / days)


def days_between(start: date, end: date) -> int:
    """Inclusive number of days in [start, end]."""
    if end < start:
        return 0
    return (end - start).days + 1


def window_end(days: int, end: date) -> date:
    """Start date of a window of `days` days ending on `end` (inclusive)."""
    return end - timedelta(days=max(days, 1) - 1)


def ceiling(value: float) -> int:
    """Smallest integer >= value (used for estimated stock-out dates)."""
    return int(math.ceil(value)) if value > 0 else 0


def trend_direction(first_avg: float, second_avg: float, threshold_pct: float) -> str:
    """UP / DOWN / STABLE based on the half-vs-half change in daily averages."""
    if first_avg <= 0 and second_avg <= 0:
        return "STABLE"
    if first_avg <= 0:
        return "UP"
    change = (second_avg - first_avg) / first_avg * 100.0
    if change >= threshold_pct:
        return "UP"
    if change <= -threshold_pct:
        return "DOWN"
    return "STABLE"


def demand_stats(
    series: dict[date, dict],
    start: date,
    end: date,
    min_history_days: int,
) -> dict:
    """Summarise demand for one store/product over [start, end].

    Returns units / revenue totals, the number of distinct days with sales,
    the pure window length used as the average denominator, and a data_status.
    """
    window_days = days_between(start, end)
    if window_days < min_history_days:
        return {
            "window_days": window_days,
            "units_sold": 0,
            "revenue": 0.0,
            "sales_days": 0,
            "average_daily_sales": 0.0,
            "data_status": "INSUFFICIENT_DATA",
        }
    units = 0.0
    revenue = 0.0
    sales_days = 0
    for day, row in series.items():
        if start <= day <= end:
            units += float(row["units"])
            revenue += float(row["revenue"])
            if row["units"] > 0:
                sales_days += 1
    return {
        "window_days": window_days,
        "units_sold": units,
        "revenue": round2(revenue),
        "sales_days": sales_days,
        "average_daily_sales": average_daily(units, window_days),
        "data_status": "SUFFICIENT",
    }