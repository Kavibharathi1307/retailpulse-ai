"""Orchestration for the deterministic analytics engine (Milestone 3).

Top-level entry points used by the API. Each function loads the raw data once
and delegates the actual calculations to the pure per-category modules, then
returns a structured, repeatable result set.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from src.analytics import anomalies, attention, data, performance, stock, velocity
from src.analytics.config import AnalyticsConfig, DEFAULT_CONFIG
from src.analytics.metrics import days_between, window_end


def _resolve_period(
    as_of_date: date,
    start_date: Optional[date],
    end_date: Optional[date],
    config: AnalyticsConfig,
) -> tuple[date, date]:
    if start_date is not None or end_date is not None:
        start = start_date or as_of_date
        end = end_date or as_of_date
        if start > end:
            raise ValueError("start_date must not be after end_date")
        return start, end
    return window_end(config.performance_period_days, as_of_date), as_of_date


def product_performance(
    db_path: Path = data.DATABASE_PATH,
    product_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    analysis_date = data.resolve_analysis_date(as_of_date, db_path)
    start, end = _resolve_period(analysis_date, start_date, end_date, config)
    prior = start - timedelta(days=days_between(start, end))
    products = data.load_products(db_path)
    sales_by_day = data.load_sales_by_day(db_path, start=prior, end=end)
    items = performance.product_performance(
        products, sales_by_day, start, end, config, analysis_date, product_id
    )
    return {
        "analysis_date": analysis_date.isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "items": items,
    }


def store_performance(
    db_path: Path = data.DATABASE_PATH,
    store_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    analysis_date = data.resolve_analysis_date(as_of_date, db_path)
    start, end = _resolve_period(analysis_date, start_date, end_date, config)
    prior = start - timedelta(days=days_between(start, end))
    stores = data.load_stores(db_path)
    sales_by_day = data.load_sales_by_day(db_path, start=prior, end=end)
    items = performance.store_performance(
        stores, sales_by_day, start, end, config, analysis_date, store_id
    )
    return {
        "analysis_date": analysis_date.isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "items": items,
    }


def _demand_context(
    db_path: Path, as_of_date: Optional[date], config: AnalyticsConfig
) -> dict:
    analysis_date = data.resolve_analysis_date(as_of_date, db_path)
    demand_start = window_end(config.demand_window_days, analysis_date)
    return {
        "analysis_date": analysis_date,
        "demand_start": demand_start,
        "demand_end": analysis_date,
    }


def stockout_risks(
    db_path: Path = data.DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    ctx = _demand_context(db_path, as_of_date, config)
    inventory = data.load_inventory(db_path, store_id=store_id, product_id=product_id)
    sales_by_day = data.load_sales_by_day(
        db_path, start=ctx["demand_start"], end=ctx["demand_end"],
        store_id=store_id, product_id=product_id,
    )
    items = stock.stockout_risks(
        inventory, sales_by_day, ctx["demand_start"], ctx["demand_end"],
        config, ctx["analysis_date"],
    )
    return {
        "analysis_date": ctx["analysis_date"].isoformat(),
        "period_start": ctx["demand_start"].isoformat(),
        "period_end": ctx["demand_end"].isoformat(),
        "items": items,
    }


def overstock(
    db_path: Path = data.DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    ctx = _demand_context(db_path, as_of_date, config)
    inventory = data.load_inventory(db_path, store_id=store_id, product_id=product_id)
    sales_by_day = data.load_sales_by_day(
        db_path, start=ctx["demand_start"], end=ctx["demand_end"],
        store_id=store_id, product_id=product_id,
    )
    items = stock.overstock(
        inventory, sales_by_day, ctx["demand_start"], ctx["demand_end"],
        config, ctx["analysis_date"],
    )
    return {
        "analysis_date": ctx["analysis_date"].isoformat(),
        "period_start": ctx["demand_start"].isoformat(),
        "period_end": ctx["demand_end"].isoformat(),
        "items": items,
    }


def slow_movers(
    db_path: Path = data.DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    ctx = _demand_context(db_path, as_of_date, config)
    inventory = data.load_inventory(db_path, store_id=store_id, product_id=product_id)
    sales_by_day = data.load_sales_by_day(
        db_path, start=ctx["demand_start"], end=ctx["demand_end"],
        store_id=store_id, product_id=product_id,
    )
    items = velocity.slow_movers(
        inventory, sales_by_day, ctx["demand_start"], ctx["demand_end"],
        config, ctx["analysis_date"],
    )
    return {
        "analysis_date": ctx["analysis_date"].isoformat(),
        "period_start": ctx["demand_start"].isoformat(),
        "period_end": ctx["demand_end"].isoformat(),
        "items": items,
    }


def sales_anomalies(
    db_path: Path = data.DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    analysis_date = data.resolve_analysis_date(as_of_date, db_path)
    scan_end = end_date or analysis_date
    scan_start = start_date or window_end(config.anomaly_scan_days, scan_end)
    if scan_start > scan_end:
        raise ValueError("start_date must not be after end_date")
    stores = data.load_stores(db_path)
    products = data.load_products(db_path)
    inventory = data.load_inventory(db_path, store_id=store_id, product_id=product_id)
    sales_by_day = data.load_sales_by_day(
        db_path, start=scan_start, end=scan_end, store_id=store_id, product_id=product_id,
    )
    segments = {(inv["store_id"], inv["product_id"]) for inv in inventory}
    segments |= set(sales_by_day.keys())
    items = anomalies.sales_anomalies(
        sorted(segments), sales_by_day, scan_start, scan_end,
        stores, products, config, analysis_date,
    )
    return {
        "analysis_date": analysis_date.isoformat(),
        "scan_window_start": scan_start.isoformat(),
        "scan_window_end": scan_end.isoformat(),
        "items": items,
    }


def attention_summary(
    db_path: Path = data.DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    as_of_date: Optional[date] = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict:
    analysis_date = data.resolve_analysis_date(as_of_date, db_path)
    stockout = stockout_risks(db_path, store_id, product_id, analysis_date, config)
    overs = overstock(db_path, store_id, product_id, analysis_date, config)
    slow = slow_movers(db_path, store_id, product_id, analysis_date, config)
    anomalies = sales_anomalies(db_path, store_id, product_id, analysis_date, None, None, config)
    items = attention.build_attention(
        stockout["items"], overs["items"], slow["items"],
        anomalies["items"], config, analysis_date,
    )
    return {
        "analysis_date": analysis_date.isoformat(),
        "counts": attention.summarize(items),
        "items": items,
    }