"""Deterministic executive intelligence (Milestone 8).

Consumes the analytics engine's existing outputs (attention, stock-out risks,
overstock, slow movers, sales anomalies, product/store performance,
recommendations, forecasts) and packages them into a decision-support summary.
It NEVER recomputes the underlying analytics: it only re-ranks and re-labels
evidence the engine already produced, so the health score, counts and top lists
are all traceable to measured numbers.

The retail health score is fully transparent:

    weighted_count = sum(severity_weight(item)) over a domain
    domain_penalty = min(1.0, weighted_count / inventory_positions)
                     * health_domain_max_penalty
    health_score   = clamp(round(100 - sum(domain_penalty)), 0, 100)

Every domain's weighted count and penalty are returned alongside the score, so
the result can always be explained mechanically. The five domains are
stock-out, forecast risk, overstock, slow movers and sales anomalies.
"""

from src.analytics.config import AnalyticsConfig
from src.analytics.metrics import round2

# Shared formula/band documentation returned with every summary.
HEALTH_FORMULA = (
    "health_score = round(100 - sum(domain_penalty)); "
    "domain_penalty = min(1.0, severity_weighted_count / inventory_positions)"
    " * 20; severity weights: stock-out CRITICAL 3.0 / HIGH 1.5 / MEDIUM 0.75,"
    " forecast AT_RISK 3.0 / WATCH 1.0, overstock 1.5, slow mover 1.5,"
    " sales spike 1.0, sales drop 2.0"
)

ISSUE_TYPE_LABELS = {
    "REPLENISH": "Stock-out risk",
    "REDUCE_INVENTORY": "Overstock",
    "REVIEW_SLOW_MOVER": "Slow mover",
    "INVESTIGATE_SALES_DROP": "Sales drop",
    "MONITOR_DEMAND": "Sales spike / demand watch",
}

OPPORTUNITY_SIGNALS = {
    "forecast_up": "Rising demand",
    "sales_spike": "Sales spike",
}
OPPORTUNITY_ACTIONS = {
    "forecast_up": "Monitor demand and confirm inventory can cover it.",
    "sales_spike": "Monitor demand and stock levels in case elevated demand continues.",
}
DECLINE_SIGNALS = {
    "forecast_down": "Declining demand",
    "sales_drop": "Sales drop",
    "slow_mover": "Slow mover",
}
DECLINE_ACTIONS = {
    "forecast_down": "Investigate the demand decline before the next replenishment.",
    "sales_drop": "Investigate the sales decline and inventory availability.",
    "slow_mover": "Review sales performance before the next replenishment cycle.",
}
FORECASTABLE_STATUSES = ("SUFFICIENT_DATA", "LIMITED_DATA")


def status_for_score(score: int, config: AnalyticsConfig) -> str:
    """Map a health score to a status band (inclusive lower bound)."""
    if score >= config.health_status_excellent:
        return "EXCELLENT"
    if score >= config.health_status_healthy:
        return "HEALTHY"
    if score >= config.health_status_watch:
        return "WATCH"
    if score >= config.health_status_at_risk:
        return "AT_RISK"
    return "CRITICAL"


def health_thresholds(config: AnalyticsConfig) -> dict:
    """Human-readable status bands, mirroring :func:`status_for_score`."""
    return {
        "EXCELLENT": f">= {config.health_status_excellent}",
        "HEALTHY": f">= {config.health_status_healthy}",
        "WATCH": f">= {config.health_status_watch}",
        "AT_RISK": f">= {config.health_status_at_risk}",
        "CRITICAL": f"< {config.health_status_at_risk}",
    }


def _domain_penalty(weighted_count: float, positions: int, config: AnalyticsConfig) -> float:
    if positions <= 0:
        return 0.0
    ratio = min(1.0, weighted_count / positions)
    return round2(ratio * config.health_domain_max_penalty)


def _count_status(rows: list[dict], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


def compute_health(
    positions: int,
    stockout_rows: list[dict],
    overstock_rows: list[dict],
    slow_rows: list[dict],
    anomaly_rows: list[dict],
    forecast_rows: list[dict],
    config: AnalyticsConfig,
) -> dict:
    """Compute a fully explainable 0-100 retail health score."""
    critical = sum(1 for r in stockout_rows if r.get("status") == "CRITICAL")
    high = sum(1 for r in stockout_rows if r.get("status") == "HIGH")
    medium = sum(1 for r in stockout_rows if r.get("status") == "MEDIUM")
    stock_weighted = (
        critical * config.health_weight_critical
        + high * config.health_weight_high
        + medium * config.health_weight_medium
    )

    forecastable = [r for r in forecast_rows if r.get("forecast_status") in FORECASTABLE_STATUSES]
    at_risk = sum(1 for r in forecastable if r.get("inventory_outlook") == "AT_RISK")
    watch = sum(1 for r in forecastable if r.get("inventory_outlook") == "WATCH")
    forecast_weighted = (
        at_risk * config.health_weight_forecast_at_risk
        + watch * config.health_weight_forecast_watch
    )

    overstock_count = _count_status(overstock_rows, "OVERSTOCK")
    slow_count = _count_status(slow_rows, "SLOW_MOVER")
    spikes = sum(1 for r in anomaly_rows if r.get("direction") == "SPIKE")
    drops = sum(1 for r in anomaly_rows if r.get("direction") == "DROP")
    anomaly_weighted = (
        spikes * config.health_weight_anomaly_spike
        + drops * config.health_weight_anomaly_drop
    )

    components = [
        {
            "key": "stock_out",
            "label": "Stock-out risk",
            "count": critical + high + medium,
            "weighted_count": round2(stock_weighted),
            "denominator": positions,
            "penalty": _domain_penalty(stock_weighted, positions, config),
            "note": (
                f"{critical} critical, {high} high, {medium} medium stock-out "
                "risks; CRITICAL carries the largest weight."
            ),
        },
        {
            "key": "forecast_risk",
            "label": "Forecast risk",
            "count": at_risk + watch,
            "weighted_count": round2(forecast_weighted),
            "denominator": positions,
            "penalty": _domain_penalty(forecast_weighted, positions, config),
            "note": (
                f"{at_risk} positions expected to run short of cover, "
                f"{watch} on watch over the forecast horizon."
            ),
        },
        {
            "key": "overstock",
            "label": "Overstock",
            "count": overstock_count,
            "weighted_count": round2(overstock_count * config.health_weight_overstock),
            "denominator": positions,
            "penalty": _domain_penalty(
                overstock_count * config.health_weight_overstock, positions, config
            ),
            "note": f"{overstock_count} positions hold stock past the cover threshold.",
        },
        {
            "key": "slow_movers",
            "label": "Slow movers",
            "count": slow_count,
            "weighted_count": round2(slow_count * config.health_weight_slow_mover),
            "denominator": positions,
            "penalty": _domain_penalty(
                slow_count * config.health_weight_slow_mover, positions, config
            ),
            "note": f"{slow_count} positions show low sales velocity.",
        },
        {
            "key": "anomalies",
            "label": "Sales anomalies",
            "count": spikes + drops,
            "weighted_count": round2(anomaly_weighted),
            "denominator": positions,
            "penalty": _domain_penalty(anomaly_weighted, positions, config),
            "note": f"{spikes} sales spikes and {drops} sales drops detected.",
        },
    ]

    penalty_total = round2(sum(component["penalty"] for component in components))
    score = max(0, round(100 - penalty_total))
    status = status_for_score(score, config)

    return {
        "score": score,
        "status": status,
        "denominator": positions,
        "formula": HEALTH_FORMULA,
        "thresholds": health_thresholds(config),
        "components": components,
        "penalty_total": penalty_total,
        "summary": _health_summary(score, status, components),
    }


def _health_summary(score: int, status: str, components: list[dict]) -> str:
    worst = max(components, key=lambda component: component["penalty"])
    if worst["penalty"] <= 0:
        return (
            f"Retail health is {status} at {score}/100, with no material penalty "
            "from any measured operational signal."
        )
    return (
        f"Retail health is {status} at {score}/100 as of the analysis date. "
        f"The largest penalty is {worst['label'].lower()} "
        f"({worst['penalty']:g} of the {worst['denominator']} weighted positions)."
    )


def _short_reason(rec: dict) -> str:
    """A one-line deterministic reason built from the recommendation's evidence."""
    etype = rec.get("type")
    evidence = rec.get("evidence") or {}
    product = rec.get("product_name") or "item"
    if etype == "REPLENISH":
        cover = evidence.get("stock_cover_days")
        threshold = evidence.get("threshold_days")
        if cover is not None and threshold is not None:
            return f"{product} runs low in {cover:g} days (threshold {threshold:g})."
        return f"{product} stock cover is below the configured threshold."
    if etype == "REDUCE_INVENTORY":
        cover = evidence.get("stock_cover_days")
        threshold = evidence.get("threshold_days")
        if cover is not None and threshold is not None:
            return f"{product} holds {cover:g} days of cover (threshold {threshold:g})."
        return f"{product} holds more stock than current demand justifies."
    if etype == "REVIEW_SLOW_MOVER":
        avg = evidence.get("average_daily_sales")
        threshold = evidence.get("threshold_daily_units")
        if avg is not None and threshold is not None:
            return f"{product} moves {avg:g} units/day (threshold {threshold:g})."
        return f"{product} shows low sales velocity."
    if etype in ("INVESTIGATE_SALES_DROP", "MONITOR_DEMAND"):
        change = evidence.get("change_pct")
        if change is not None:
            direction = "below" if etype == "INVESTIGATE_SALES_DROP" else "above"
            return f"{product} recent demand ran {abs(change):g}% {direction} baseline."
        return f"{product} shows a notable recent change in demand."
    return rec.get("reason") or ""


def build_top_issues(recommendation_items: list[dict], limit: int) -> list[dict]:
    """Rank the most urgent deterministic recommendations (CRITICAL/HIGH first)."""
    prioritized = [r for r in recommendation_items if r.get("priority") != "LOW"]
    source = prioritized or list(recommendation_items)
    entries = []
    for rank, rec in enumerate(source[:limit], start=1):
        entries.append(
            {
                "rank": rank,
                "issue_type": ISSUE_TYPE_LABELS.get(rec.get("type"), rec.get("type")),
                "recommendation_type": rec.get("type"),
                "priority": rec.get("priority"),
                "product": rec.get("product_name"),
                "store": rec.get("store_name"),
                "product_id": rec.get("product_id"),
                "store_id": rec.get("store_id"),
                "short_reason": _short_reason(rec),
                "reason": rec.get("reason"),
                "evidence": rec.get("evidence"),
                "recommended_action": rec.get("action"),
                "data_status": rec.get("data_status"),
            }
        )
    return entries


def _trend_change_pct(recent: float, baseline: float) -> float | None:
    if baseline:
        return round2((recent - baseline) / baseline * 100.0)
    return None


def build_top_opportunities(
    forecast_items: list[dict],
    anomaly_items: list[dict],
    limit: int,
    config: AnalyticsConfig,
) -> list[dict]:
    """Rising-demand products (forecast UP) plus confirmed sales spikes."""
    seen: set[tuple] = set()
    rows: list[dict] = []
    for row in forecast_items:
        if row.get("trend") != "UP" or row.get("forecast_status") not in FORECASTABLE_STATUSES:
            continue
        key = (row.get("store_id"), row.get("product_id"))
        if key in seen:
            continue
        seen.add(key)
        recent = row.get("recent_daily_demand")
        baseline = row.get("baseline_daily_demand")
        rows.append(
            {
                "category": "Demand opportunity",
                "signal": OPPORTUNITY_SIGNALS["forecast_up"],
                "sort_value": recent or 0,
                "product": row.get("product_name"),
                "store": row.get("store_name"),
                "product_id": row.get("product_id"),
                "store_id": row.get("store_id"),
                "metric": "recent_daily_demand",
                "value": recent,
                "trend": row.get("trend"),
                "change_pct": _trend_change_pct(recent, baseline) if recent is not None else None,
                "reason": (
                    f"Recent demand of {recent:g} units/day is "
                    f"{_pct_phrase(_trend_change_pct(recent, baseline))} the earlier "
                    f"average of {baseline:g} units/day."
                ),
                "evidence": {
                    "recent_daily_demand": recent,
                    "baseline_daily_demand": baseline,
                    "trend_change_pct": _trend_change_pct(recent, baseline),
                    "forecast_units": row.get("forecast_units"),
                    "horizon_days": row.get("horizon_days"),
                    "trend": row.get("trend"),
                    "trend_threshold_pct": config.forecast_trend_threshold_pct,
                    "inventory_outlook": row.get("inventory_outlook"),
                },
                "recommended_action": OPPORTUNITY_ACTIONS["forecast_up"],
                "data_status": row.get("forecast_status"),
            }
        )
    for row in anomaly_items:
        if row.get("direction") != "SPIKE":
            continue
        key = (row.get("store_id"), row.get("product_id"))
        if key in seen:
            continue
        seen.add(key)
        change = row.get("change_pct")
        recent_units = row.get("recent_units")
        baseline_units = row.get("baseline_units")
        rows.append(
            {
                "category": "Demand opportunity",
                "signal": OPPORTUNITY_SIGNALS["sales_spike"],
                "sort_value": (row.get("evidence") or {}).get("recent_daily_rate") or recent_units or 0,
                "product": row.get("product_name"),
                "store": row.get("store_name"),
                "product_id": row.get("product_id"),
                "store_id": row.get("store_id"),
                "metric": "change_pct",
                "value": change,
                "trend": "UP",
                "change_pct": change,
                "reason": (
                    f"Recent sales of {recent_units:g} units ran {abs(change):g}% "
                    f"above baseline of {baseline_units:g} units."
                ),
                "evidence": {
                    "recent_units": recent_units,
                    "baseline_units": baseline_units,
                    "change_pct": change,
                    **(row.get("evidence") or {}),
                },
                "recommended_action": OPPORTUNITY_ACTIONS["sales_spike"],
                "data_status": row.get("data_status"),
            }
        )
    rows.sort(key=lambda r: r["sort_value"], reverse=True)
    return [_ranked_entry(row, rank) for rank, row in enumerate(rows[:limit], start=1)]


def build_top_declines(
    forecast_items: list[dict],
    anomaly_items: list[dict],
    slow_items: list[dict],
    limit: int,
    config: AnalyticsConfig,
) -> list[dict]:
    """Declining-demand products: forecast DOWN, sales drops and slow movers."""
    seen: set[tuple] = set()
    rows: list[dict] = []
    for row in forecast_items:
        if row.get("trend") != "DOWN" or row.get("forecast_status") not in FORECASTABLE_STATUSES:
            continue
        key = (row.get("store_id"), row.get("product_id"))
        if key in seen:
            continue
        seen.add(key)
        recent = row.get("recent_daily_demand")
        baseline = row.get("baseline_daily_demand")
        rows.append(
            {
                "category": "Declining demand",
                "signal": DECLINE_SIGNALS["forecast_down"],
                "sort_value": recent or 0,
                "product": row.get("product_name"),
                "store": row.get("store_name"),
                "product_id": row.get("product_id"),
                "store_id": row.get("store_id"),
                "metric": "recent_daily_demand",
                "value": recent,
                "trend": row.get("trend"),
                "change_pct": _trend_change_pct(recent, baseline) if recent is not None else None,
                "reason": (
                    f"Recent demand of {recent:g} units/day is "
                    f"{_pct_phrase(_trend_change_pct(recent, baseline))} the earlier "
                    f"average of {baseline:g} units/day."
                ),
                "evidence": {
                    "recent_daily_demand": recent,
                    "baseline_daily_demand": baseline,
                    "trend_change_pct": _trend_change_pct(recent, baseline),
                    "forecast_units": row.get("forecast_units"),
                    "horizon_days": row.get("horizon_days"),
                    "trend": row.get("trend"),
                    "trend_threshold_pct": config.forecast_trend_threshold_pct,
                    "inventory_outlook": row.get("inventory_outlook"),
                },
                "recommended_action": DECLINE_ACTIONS["forecast_down"],
                "data_status": row.get("forecast_status"),
            }
        )
    for row in anomaly_items:
        if row.get("direction") != "DROP":
            continue
        key = (row.get("store_id"), row.get("product_id"))
        if key in seen:
            continue
        seen.add(key)
        change = row.get("change_pct")
        recent_units = row.get("recent_units")
        baseline_units = row.get("baseline_units")
        rows.append(
            {
                "category": "Declining demand",
                "signal": DECLINE_SIGNALS["sales_drop"],
                "sort_value": (row.get("evidence") or {}).get("recent_daily_rate") or recent_units or 0,
                "product": row.get("product_name"),
                "store": row.get("store_name"),
                "product_id": row.get("product_id"),
                "store_id": row.get("store_id"),
                "metric": "change_pct",
                "value": change,
                "trend": "DOWN",
                "change_pct": change,
                "reason": (
                    f"Recent sales of {recent_units:g} units ran {abs(change):g}% "
                    f"below baseline of {baseline_units:g} units."
                ),
                "evidence": {
                    "recent_units": recent_units,
                    "baseline_units": baseline_units,
                    "change_pct": change,
                    **(row.get("evidence") or {}),
                },
                "recommended_action": DECLINE_ACTIONS["sales_drop"],
                "data_status": row.get("data_status"),
            }
        )
    for row in slow_items:
        if row.get("status") != "SLOW_MOVER" or row.get("data_status") != "SUFFICIENT":
            continue
        key = (row.get("store_id"), row.get("product_id"))
        if key in seen:
            continue
        seen.add(key)
        avg = row.get("average_daily_sales")
        rows.append(
            {
                "category": "Declining demand",
                "signal": DECLINE_SIGNALS["slow_mover"],
                "sort_value": avg or 0,
                "product": row.get("product_name"),
                "store": row.get("store_name"),
                "product_id": row.get("product_id"),
                "store_id": row.get("store_id"),
                "metric": "average_daily_sales",
                "value": avg,
                "trend": "STABLE",
                "change_pct": None,
                "reason": (
                    f"{row.get('product_name')} averages {avg:g} units/day "
                    f"({row.get('units_sold'):g} units over {row.get('sales_days'):g} selling days)."
                ),
                "evidence": {
                    "average_daily_sales": avg,
                    "units_sold": row.get("units_sold"),
                    "sales_days": row.get("sales_days"),
                    "threshold_daily_units": row.get("threshold_daily_units"),
                    "period_start": row.get("period_start"),
                    "period_end": row.get("period_end"),
                },
                "recommended_action": DECLINE_ACTIONS["slow_mover"],
                "data_status": row.get("data_status"),
            }
        )
    rows.sort(key=lambda r: r["sort_value"], reverse=True)
    return [_ranked_entry(row, rank) for rank, row in enumerate(rows[:limit], start=1)]


def _pct_phrase(change_pct: float | None) -> str:
    if change_pct is None:
        return "compared to"
    return f"{abs(change_pct):g}% {'above' if change_pct >= 0 else 'below'}"


def _ranked_entry(row: dict, rank: int) -> dict:
    return {key: value for key, value in row.items() if key != "sort_value"} | {"rank": rank}


def build_summary(
    analysis_date: str,
    horizon_days: int,
    positions: int,
    total_stores: int,
    total_products: int,
    total_revenue: float,
    total_units: int,
    stockout_rows: list[dict],
    overstock_rows: list[dict],
    slow_rows: list[dict],
    anomaly_rows: list[dict],
    attention_items: list[dict],
    recommendation_items: list[dict],
    recommendation_counts: dict,
    forecast_items: list[dict],
    forecast_counts: dict,
    forecast_status: str,
    expected_daily_demand: float,
    expected_horizon_units: float,
    forecast_method: str,
    config: AnalyticsConfig,
    limit: int,
) -> dict:
    """Compose a deterministic executive summary from engine outputs."""
    health = compute_health(
        positions, stockout_rows, overstock_rows, slow_rows, anomaly_rows,
        forecast_items, config,
    )

    critical_issue_count = sum(1 for a in attention_items if a.get("severity") == "CRITICAL")
    high_issue_count = sum(1 for a in attention_items if a.get("severity") == "HIGH")
    stockout_risk_count = sum(
        1 for r in stockout_rows if r.get("status") in ("CRITICAL", "HIGH")
    )
    overstock_count = _count_status(overstock_rows, "OVERSTOCK")
    slow_mover_count = _count_status(slow_rows, "SLOW_MOVER")
    anomaly_count = sum(1 for r in anomaly_rows if r.get("direction") in ("SPIKE", "DROP"))
    forecast_at_risk_count = (forecast_counts.get("by_inventory_outlook") or {}).get("AT_RISK", 0)
    rising_product_count = (forecast_counts.get("by_trend") or {}).get("UP", 0)
    declining_product_count = (forecast_counts.get("by_trend") or {}).get("DOWN", 0)
    recommendation_count = recommendation_counts.get("total", len(recommendation_items))

    counts = {
        "total_stores": total_stores,
        "total_products": total_products,
        "total_revenue": round2(total_revenue),
        "total_units": int(total_units),
        "critical_issue_count": critical_issue_count,
        "high_issue_count": high_issue_count,
        "recommendation_count": recommendation_count,
        "forecast_at_risk_count": forecast_at_risk_count,
        "rising_product_count": rising_product_count,
        "declining_product_count": declining_product_count,
        "stockout_risk_count": stockout_risk_count,
        "overstock_count": overstock_count,
        "slow_mover_count": slow_mover_count,
        "anomaly_count": anomaly_count,
    }

    return {
        "analysis_date": analysis_date,
        "as_of_date": analysis_date,
        "health": health,
        "counts": counts,
        "business_snapshot": {
            "total_stores": total_stores,
            "total_products": total_products,
            "total_revenue": round2(total_revenue),
            "total_units": int(total_units),
        },
        "inventory_snapshot": {
            "total_inventory_records": positions,
            "critical_stockout": sum(1 for r in stockout_rows if r.get("status") == "CRITICAL"),
            "high_stockout": sum(1 for r in stockout_rows if r.get("status") == "HIGH"),
            "medium_stockout": sum(1 for r in stockout_rows if r.get("status") == "MEDIUM"),
            "overstock": overstock_count,
            "slow_movers": slow_mover_count,
            "forecast_at_risk": forecast_at_risk_count,
        },
        "top_issues": build_top_issues(recommendation_items, limit),
        "top_opportunities": build_top_opportunities(
            forecast_items, anomaly_rows, limit, config
        ),
        "top_declines": build_top_declines(
            forecast_items, anomaly_rows, slow_rows, limit, config
        ),
        "forecast_snapshot": {
            "horizon_days": horizon_days,
            "forecast_status": forecast_status,
            "expected_daily_demand": round2(expected_daily_demand),
            "expected_horizon_units": round2(expected_horizon_units),
            "method": forecast_method,
            "counts": forecast_counts,
        },
        "recommendation_snapshot": recommendation_counts,
    }