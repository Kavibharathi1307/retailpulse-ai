"""Deterministic, explainable short-horizon demand forecasting (Milestone 7).

The forecast is a plain "carry the recent demand rate forward" estimate:

    forecast_units = recent_daily_rate * horizon_days

where the recent daily rate is measured over a short recent window ending at
the analysis date. A longer preceding baseline window is only used to classify
the trend (UP / STABLE / DOWN); it never changes the forecast numbers. This is
deliberately simple and fully reproducible -- no model, no probability, no
black box -- so every number can be explained to a store manager.

Data sufficiency:
    * INSUFFICIENT_DATA -- the recent window is not fully covered by sales
      history, so no demand rate exists and NOTHING is fabricated.
    * LIMITED_DATA     -- the recent window is covered but the baseline window
      is thinner than ideal; the forecast still ships but is flagged.
    * SUFFICIENT_DATA  -- both windows are covered to the configured minimum.

Inventory outlook compares current stock to the expected demand over the
horizon (never a fabricated future stock-out date):
    * AT_RISK   when current_stock < forecast_units
    * WATCH     when forecast_units <= current_stock < forecast_units * (1+buffer)
    * SUFFICIENT otherwise.
"""

from collections import Counter
from datetime import date, timedelta

from src.analytics.config import AnalyticsConfig
from src.analytics.metrics import days_between, round1, round2, trend_direction


def _covered_days(
    window_start: date, window_end: date, history_start: date
) -> int:
    """Calendar days of the window that fall within the dataset history."""
    effective_start = max(window_start, history_start)
    if effective_start > window_end:
        return 0
    return days_between(effective_start, window_end)


def _window_measure(
    series: dict[date, dict],
    window_start: date,
    window_end: date,
    history_start: date,
) -> tuple[float, int, date, int]:
    """Sum units in [start, end] intersected with history; return covered days.

    Returns (units, covered_days, effective_start, full_window_days). The
    effective start is the later of the window start and the dataset start, so
    the average denominator always matches the days actually observed.
    """
    full_window_days = days_between(window_start, window_end)
    effective_start = max(window_start, history_start)
    covered = days_between(effective_start, window_end) if effective_start <= window_end else 0
    units = 0.0
    for day, row in series.items():
        if effective_start <= day <= window_end:
            units += float(row["units"])
    return units, covered, effective_start, full_window_days


def _classify_forecast_status(
    recent_covered: int,
    baseline_covered: int,
    config: AnalyticsConfig,
) -> str:
    if recent_covered < config.forecast_min_recent_days:
        return "INSUFFICIENT_DATA"
    if baseline_covered < config.forecast_min_baseline_days:
        return "LIMITED_DATA"
    return "SUFFICIENT_DATA"


def _classify_trend(
    recent_daily: float, baseline_daily: float, config: AnalyticsConfig
) -> str:
    if recent_daily <= 0 and baseline_daily <= 0:
        return "STABLE"
    if baseline_daily <= 0:
        return "UP"
    direction = trend_direction(
        baseline_daily, recent_daily, config.forecast_trend_threshold_pct
    )
    return direction


def _classify_inventory_outlook(
    current_stock: float, forecast_units: float, config: AnalyticsConfig
) -> str:
    if forecast_units <= 0:
        return "SUFFICIENT"
    ratio = current_stock / forecast_units
    if ratio < 1.0:
        return "AT_RISK"
    if ratio < 1.0 + config.forecast_inventory_buffer_pct / 100.0:
        return "WATCH"
    return "SUFFICIENT"


def forecast_rows(
    inventory: list[dict],
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    analysis_date: date,
    horizon_days: int,
    history_start: date,
    config: AnalyticsConfig,
) -> list[dict]:
    """Short-horizon demand forecast + inventory outlook for every segment."""
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")

    recent_window_days = config.forecast_recent_days
    baseline_window_days = config.forecast_baseline_days
    recent_start = analysis_date - timedelta(days=recent_window_days - 1)
    baseline_end = analysis_date - timedelta(days=recent_window_days)
    baseline_start = baseline_end - timedelta(days=baseline_window_days - 1)

    rows = []
    for inv in inventory:
        sid, pid = inv["store_id"], inv["product_id"]
        series = sales_by_day.get((sid, pid), {})

        recent_units, recent_covered, recent_eff_start, _ = _window_measure(
            series, recent_start, analysis_date, history_start
        )
        baseline_units, baseline_covered, baseline_eff_start, _ = _window_measure(
            series, baseline_start, baseline_end, history_start
        )

        status = _classify_forecast_status(recent_covered, baseline_covered, config)

        if status == "INSUFFICIENT_DATA" or recent_covered <= 0:
            rows.append(
                {
                    "store_id": sid,
                    "store_name": inv["store_name"],
                    "product_id": pid,
                    "product_name": inv["product_name"],
                    "analysis_date": analysis_date.isoformat(),
                    "horizon_days": horizon_days,
                    "forecast_status": "INSUFFICIENT_DATA",
                    "recent_daily_demand": None,
                    "baseline_daily_demand": None,
                    "forecast_units": None,
                    "trend": "UNKNOWN",
                    "current_stock": int(inv["current_stock"]),
                    "expected_cover_days": None,
                    "inventory_outlook": "INSUFFICIENT_DATA",
                    "method": (
                        "carry the recent daily demand rate over the horizon "
                        "days after the analysis date"
                    ),
                    "evidence": {
                        "history_start": history_start.isoformat(),
                        "analysis_date": analysis_date.isoformat(),
                        "recent_window_start": recent_eff_start.isoformat(),
                        "recent_window_end": analysis_date.isoformat(),
                        "recent_window_days": recent_covered,
                        "recent_units": int(recent_units),
                        "baseline_window_start": (
                            baseline_eff_start.isoformat()
                            if baseline_covered > 0
                            else None
                        ),
                        "baseline_window_end": baseline_end.isoformat(),
                        "baseline_window_days": baseline_covered,
                        "baseline_units": int(baseline_units),
                        "horizon_days": horizon_days,
                        "required_recent_days": config.forecast_min_recent_days,
                        "required_baseline_days": config.forecast_min_baseline_days,
                        "trend_threshold_pct": config.forecast_trend_threshold_pct,
                        "inventory_buffer_pct": config.forecast_inventory_buffer_pct,
                    },
                    "explanation": (
                        "Insufficient sales history within the recent demand "
                        f"window ({recent_covered} of {recent_window_days} days "
                        f"covered) to estimate a reliable {horizon_days}-day "
                        "forecast. No forecast numbers are produced."
                    ),
                }
            )
            continue

        recent_daily = round2(recent_units / recent_covered) if recent_covered else 0.0
        baseline_daily = round2(baseline_units / baseline_covered) if baseline_covered else 0.0
        forecast_units = round1(recent_daily * horizon_days)
        trend = _classify_trend(recent_daily, baseline_daily, config)
        expected_cover_days = (
            round1(inv["current_stock"] / recent_daily) if recent_daily > 0 else None
        )
        inventory_outlook = _classify_inventory_outlook(
            inv["current_stock"], forecast_units, config
        )

        rows.append(
            {
                "store_id": sid,
                "store_name": inv["store_name"],
                "product_id": pid,
                "product_name": inv["product_name"],
                "analysis_date": analysis_date.isoformat(),
                "horizon_days": horizon_days,
                "forecast_status": status,
                "recent_daily_demand": recent_daily,
                "baseline_daily_demand": baseline_daily,
                "forecast_units": forecast_units,
                "trend": trend,
                "current_stock": int(inv["current_stock"]),
                "expected_cover_days": expected_cover_days,
                "inventory_outlook": inventory_outlook,
                "method": (
                    "carry the recent daily demand rate over the horizon days "
                    "after the analysis date; baseline window used only for trend"
                ),
                "evidence": {
                    "history_start": history_start.isoformat(),
                    "analysis_date": analysis_date.isoformat(),
                    "recent_window_start": recent_eff_start.isoformat(),
                    "recent_window_end": analysis_date.isoformat(),
                    "recent_window_days": recent_covered,
                    "recent_units": int(recent_units),
                    "baseline_window_start": (
                        baseline_eff_start.isoformat() if baseline_covered > 0 else None
                    ),
                    "baseline_window_end": baseline_end.isoformat(),
                    "baseline_window_days": baseline_covered,
                    "baseline_units": int(baseline_units),
                    "horizon_days": horizon_days,
                    "required_recent_days": config.forecast_min_recent_days,
                    "required_baseline_days": config.forecast_min_baseline_days,
                    "trend_threshold_pct": config.forecast_trend_threshold_pct,
                    "inventory_buffer_pct": config.forecast_inventory_buffer_pct,
                },
                "explanation": (
                    f"Recent demand rate of {recent_daily:g} units/day over "
                    f"{recent_covered} days extended over the {horizon_days}-day "
                    f"horizon gives expected demand of {forecast_units:g} units. "
                    f"Baseline rate {baseline_daily:g} units/day over "
                    f"{baseline_covered} days is used for the "
                    f"{trend} trend (threshold {config.forecast_trend_threshold_pct:g}%)."
                ),
            }
        )
    return rows


def summarize(items: list[dict]) -> dict:
    """Counts by forecast status, trend, and inventory outlook."""
    counts = {
        "total": len(items),
        "by_forecast_status": dict(Counter(item["forecast_status"] for item in items)),
        "by_trend": dict(Counter(item["trend"] for item in items)),
        "by_inventory_outlook": dict(
            Counter(item["inventory_outlook"] for item in items)
        ),
    }
    return counts


def aggregate_status(items: list[dict]) -> str:
    """Best available status across rows; transparent thanks to the counts."""
    for status in ("SUFFICIENT_DATA", "LIMITED_DATA", "INSUFFICIENT_DATA"):
        if any(item["forecast_status"] == status for item in items):
            return status
    return "INSUFFICIENT_DATA"


def demand_outlook(items: list[dict], horizon_days: int) -> tuple[float, float, int]:
    """Aggregate expected daily demand and horizon totals across forecastable rows.

    Returns (expected_daily_demand, expected_horizon_units, forecastable_total)
    counting only SUFFICIENT_DATA / LIMITED_DATA rows so no fabricated numbers
    are ever aggregated.
    """
    forecastable = [
        item
        for item in items
        if item["forecast_status"] in ("SUFFICIENT_DATA", "LIMITED_DATA")
    ]
    daily = round2(
        sum(item["recent_daily_demand"] or 0.0 for item in forecastable)
    )
    horizon_units = round1(daily * horizon_days)
    return daily, horizon_units, len(forecastable)


def outlook_summary(items: list[dict], horizon_days: int) -> dict:
    """Compact summary consumed by /forecast-summary and the dashboard."""
    counts = summarize(items)
    daily, horizon_units, forecastable = demand_outlook(items, horizon_days)
    return {
        "forecast_status": aggregate_status(items),
        "counts": counts,
        "expected_daily_demand": daily,
        "expected_horizon_units": horizon_units,
        "forecastable_total": forecastable,
    }