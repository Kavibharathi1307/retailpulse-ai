"""Sales spike/drop detection (Milestone 3, section E).

For each store/product segment the engine walks a rolling recent window across
the scan range and compares its average daily rate against the preceding
baseline window:

    recent_daily_rate   = recent_units / recent_days
    baseline_daily_rate = baseline_units / baseline_days
    change_pct          = (recent_daily_rate - baseline_daily_rate)
                          / baseline_daily_rate * 100

Classification of the strongest qualifying event per segment:

    SPIKE  when change_pct >= spike_threshold_pct and recent_units >= min_change_units
    DROP   when change_pct <= -drop_threshold_pct
    NORMAL otherwise

Volume safeguards prevent tiny numbers from being presented as business-changing
anomalies: baseline window totals must reach min_baseline_units before a
candidate is even considered.
"""

from datetime import date, timedelta

from src.analytics.config import AnalyticsConfig
from src.analytics.metrics import round1, round2


def _base_row(
    sid: int,
    pid: int,
    stores: dict[int, dict],
    products: dict[int, dict],
    analysis_date: date,
    scan_start: date,
    scan_end: date,
    config: AnalyticsConfig,
    direction: str,
    data_status: str,
) -> dict:
    store = stores.get(sid)
    product = products.get(pid)
    return {
        "store_id": sid,
        "store_name": store["store_name"] if store else None,
        "product_id": pid,
        "product_name": product["product_name"] if product else None,
        "analysis_date": analysis_date.isoformat(),
        "scan_window_start": scan_start.isoformat(),
        "scan_window_end": scan_end.isoformat(),
        "recent_days": config.anomaly_recent_days,
        "baseline_days": config.anomaly_baseline_days,
        "recent_units": None,
        "baseline_units": None,
        "change_pct": None,
        "absolute_change": None,
        "direction": direction,
        "data_status": data_status,
        "thresholds": {
            "spike_threshold_pct": config.spike_threshold_pct,
            "drop_threshold_pct": config.drop_threshold_pct,
            "min_baseline_units": config.min_baseline_units,
            "min_recent_units": config.min_anomaly_change_units,
        },
        "evidence": {},
        "explanation": "",
    }


def sales_anomalies(
    segments: list[tuple[int, int]],
    sales_by_day: dict[tuple[int, int], dict[date, dict]],
    scan_start: date,
    scan_end: date,
    stores: dict[int, dict],
    products: dict[int, dict],
    config: AnalyticsConfig,
    analysis_date: date,
) -> list[dict]:
    """Detect the strongest qualifying spike/drop per store/product segment."""
    recent_days = config.anomaly_recent_days
    baseline_days = config.anomaly_baseline_days
    rows = []
    for sid, pid in segments:
        series = sales_by_day.get((sid, pid), {})
        relevant = sorted(d for d in series if scan_start <= d <= scan_end)

        candidates = []
        for day in relevant:
            recent_start = day - timedelta(days=recent_days - 1)
            baseline_end = recent_start - timedelta(days=1)
            baseline_start = baseline_end - timedelta(days=baseline_days - 1)
            if baseline_start < scan_start:
                continue
            recent_units = sum(
                float(series[d]["units"]) for d in series if recent_start <= d <= day
            )
            baseline_units = sum(
                float(series[d]["units"]) for d in series if baseline_start <= d <= baseline_end
            )
            if baseline_units < config.min_baseline_units:
                continue
            baseline_rate = baseline_units / baseline_days
            recent_rate = recent_units / recent_days
            change_pct = (
                (recent_rate - baseline_rate) / baseline_rate * 100.0
                if baseline_rate > 0
                else 0.0
            )
            candidates.append(
                {
                    "day": day,
                    "recent_units": recent_units,
                    "baseline_units": baseline_units,
                    "recent_daily_rate": recent_rate,
                    "baseline_daily_rate": baseline_rate,
                    "change_pct": change_pct,
                    "recent_start": recent_start,
                    "baseline_start": baseline_start,
                    "baseline_end": baseline_end,
                }
            )

        row = _base_row(
            sid, pid, stores, products, analysis_date, scan_start, scan_end,
            config, "NORMAL", "SUFFICIENT",
        )
        if not candidates:
            row["direction"] = "INSUFFICIENT_DATA"
            row["data_status"] = "INSUFFICIENT_DATA"
            row["explanation"] = (
                "Not enough sales history or volume in the scan window to detect anomalies."
            )
            rows.append(row)
            continue

        best = None
        for candidate in candidates:
            direction = None
            if (
                candidate["change_pct"] >= config.spike_threshold_pct
                and candidate["recent_units"] >= config.min_anomaly_change_units
            ):
                direction = "SPIKE"
            elif (
                candidate["change_pct"] <= -config.drop_threshold_pct
                and (candidate["baseline_units"] - candidate["recent_units"])
                >= config.min_anomaly_change_units
            ):
                direction = "DROP"
            if direction:
                candidate["direction"] = direction
                if best is None or abs(candidate["change_pct"]) > abs(best["change_pct"]):
                    best = candidate

        if best is None:
            row["explanation"] = _explanation("NORMAL", None)
            rows.append(row)
            continue

        row["direction"] = best["direction"]
        row.update(
            {
                "recent_units": round2(best["recent_units"]),
                "baseline_units": round2(best["baseline_units"]),
                "change_pct": round1(best["change_pct"]),
                "absolute_change": round2(best["recent_units"] - best["baseline_units"]),
                "evidence": {
                    "recent_window_start": best["recent_start"].isoformat(),
                    "recent_window_end": best["day"].isoformat(),
                    "baseline_window_start": best["baseline_start"].isoformat(),
                    "baseline_window_end": best["baseline_end"].isoformat(),
                    "recent_daily_rate": round2(best["recent_daily_rate"]),
                    "baseline_daily_rate": round2(best["baseline_daily_rate"]),
                },
                "explanation": _explanation(best["direction"], best),
            }
        )
        rows.append(row)
    return rows


def _explanation(direction: str, best: dict) -> str:
    if direction == "SPIKE":
        return (
            f"Recent daily rate of {round2(best['recent_daily_rate'])} units/day is "
            f"{round1(best['change_pct'])}% higher than baseline of "
            f"{round2(best['baseline_daily_rate'])} units/day."
        )
    if direction == "DROP":
        return (
            f"Recent daily rate of {round2(best['recent_daily_rate'])} units/day is "
            f"{round1(best['change_pct'])}% lower than baseline of "
            f"{round2(best['baseline_daily_rate'])} units/day."
        )
    return "No recent sales change exceeded the spike/drop thresholds."