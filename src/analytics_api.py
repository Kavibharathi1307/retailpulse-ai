"""Analytics API endpoints (Milestone 3).

Deterministic, rule-based insights exposed under /api/analytics. Every response
carries the analysis_date and the evidence behind each finding so a future AI
layer can ground its answers in these numbers.
"""

import sqlite3
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src import repositories
from src.analytics import data as analytics_data
from src.analytics import engine as analytics_engine
import importlib

analytics_recommendations = importlib.import_module("src.analytics.recommendations")
from src.analytics.config import DEFAULT_CONFIG
from src.config import DATABASE_PATH

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

VALID_PRIORITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

VALID_RECOMMENDATION_TYPES = {
    "REPLENISH",
    "REDUCE_INVENTORY",
    "REVIEW_SLOW_MOVER",
    "INVESTIGATE_SALES_DROP",
    "MONITOR_DEMAND",
}

VALID_FORECAST_HORIZONS = DEFAULT_CONFIG.forecast_valid_horizons


def _bounded_limit(limit: int) -> int:
    if limit < 0 or limit > MAX_LIMIT:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_limit",
                "message": f"limit must be between 0 and {MAX_LIMIT}",
            },
        )
    return limit


def _offset(offset: int) -> int:
    if offset < 0:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_offset", "message": "offset must be >= 0"},
        )
    return offset


def _require_resource(exists: bool, resource: str, resource_id: int) -> None:
    if not exists:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"{resource} {resource_id} does not exist",
            },
        )


def _validate_references(store_id=None, product_id=None) -> None:
    if store_id is not None and not repositories.store_exists(store_id=store_id):
        _require_resource(False, "store", store_id)
    if product_id is not None and not repositories.product_exists(product_id=product_id):
        _require_resource(False, "product", product_id)


def _validate_analysis_date(as_of_date: Optional[date]) -> Optional[date]:
    """Reject as_of_date outside the committed dataset's date range."""
    if as_of_date is None:
        return None
    bounds = analytics_data.dataset_date_range(DATABASE_PATH)
    if bounds is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "no_sales_data",
                "message": "The retail database has no sales history to analyse.",
            },
        )
    first, last = bounds
    if not (first <= as_of_date <= last):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_as_of_date",
                "message": (
                    f"as_of_date must be within the dataset range "
                    f"{first.isoformat()}..{last.isoformat()}"
                ),
            },
        )
    return as_of_date


def _validate_period(start_date: Optional[date], end_date: Optional[date]) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_range", "message": "start_date must not be after end_date"},
        )


def _run(operation) -> dict:
    try:
        return operation()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "The retail database is currently unavailable.",
            },
        ) from exc


def _page(items: list, limit: int, offset: int) -> dict:
    total = len(items)
    return {"items": items[offset : offset + limit], "total": total, "limit": limit, "offset": offset}


@router.get("/attention-summary")
def attention_summary(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id, product_id)
    summary = _run(
        lambda: analytics_engine.attention_summary(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": summary["analysis_date"],
        "counts": summary["counts"],
        **_page(summary["items"], limit, offset),
    }


@router.get("/stock-out-risks")
def stock_out_risks(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id, product_id)
    result = _run(
        lambda: analytics_engine.stockout_risks(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": result["analysis_date"],
        "period_start": result["period_start"],
        "period_end": result["period_end"],
        **_page(result["items"], limit, offset),
    }


@router.get("/overstock")
def overstock(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id, product_id)
    result = _run(
        lambda: analytics_engine.overstock(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": result["analysis_date"],
        "period_start": result["period_start"],
        "period_end": result["period_end"],
        **_page(result["items"], limit, offset),
    }


@router.get("/slow-movers")
def slow_movers(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id, product_id)
    result = _run(
        lambda: analytics_engine.slow_movers(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": result["analysis_date"],
        "period_start": result["period_start"],
        "period_end": result["period_end"],
        **_page(result["items"], limit, offset),
    }


@router.get("/sales-anomalies")
def sales_anomalies(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_period(start_date, end_date)
    _validate_references(store_id, product_id)
    result = _run(
        lambda: analytics_engine.sales_anomalies(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": result["analysis_date"],
        "scan_window_start": result["scan_window_start"],
        "scan_window_end": result["scan_window_end"],
        **_page(result["items"], limit, offset),
    }


@router.get("/product-performance")
def product_performance(
    product_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_period(start_date, end_date)
    if product_id is not None and not repositories.product_exists(product_id=product_id):
        _require_resource(False, "product", product_id)
    result = _run(
        lambda: analytics_engine.product_performance(
            db_path=DATABASE_PATH,
            product_id=product_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": result["analysis_date"],
        "period_start": result["period_start"],
        "period_end": result["period_end"],
        **_page(result["items"], limit, offset),
    }


@router.get("/store-performance")
def store_performance(
    store_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_period(start_date, end_date)
    if store_id is not None and not repositories.store_exists(store_id=store_id):
        _require_resource(False, "store", store_id)
    result = _run(
        lambda: analytics_engine.store_performance(
            db_path=DATABASE_PATH,
            store_id=store_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": result["analysis_date"],
        "period_start": result["period_start"],
        "period_end": result["period_end"],
        **_page(result["items"], limit, offset),
    }


@router.get("/recommendations")
def recommendations(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    priority: Optional[str] = Query(None),
    recommendation_type: Optional[str] = Query(None),
    as_of_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id, product_id)
    if priority is not None and priority.upper() not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_priority",
                "message": (
                    "priority must be one of "
                    + ", ".join(sorted(VALID_PRIORITIES))
                ),
            },
        )
    if (
        recommendation_type is not None
        and recommendation_type.upper() not in VALID_RECOMMENDATION_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_recommendation_type",
                "message": (
                    "recommendation_type must be one of "
                    + ", ".join(sorted(VALID_RECOMMENDATION_TYPES))
                ),
            },
        )
    result = _run(
        lambda: analytics_recommendations.recommendations(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            config=DEFAULT_CONFIG,
        )
    )
    items = result["items"]
    if priority is not None:
        items = [item for item in items if item["priority"] == priority.upper()]
    if recommendation_type is not None:
        items = [item for item in items if item["type"] == recommendation_type.upper()]
    return {
        "analysis_date": result["analysis_date"],
        "counts": result["counts"],
        **_page(items, limit, offset),
    }


def _validate_horizon(horizon_days: Optional[int]) -> int:
    if horizon_days is None:
        return 7
    if horizon_days not in VALID_FORECAST_HORIZONS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_horizon_days",
                "message": (
                    "horizon_days must be one of "
                    + ", ".join(str(h) for h in sorted(VALID_FORECAST_HORIZONS))
                ),
            },
        )
    return horizon_days


@router.get("/forecast")
def forecast(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    horizon_days: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_LIMIT),
    offset: int = Query(0),
) -> dict:
    """Deterministic short-horizon demand forecast per store/product."""
    limit = _bounded_limit(limit)
    offset = _offset(offset)
    horizon_days = _validate_horizon(horizon_days)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id, product_id)
    result = _run(
        lambda: analytics_engine.forecast(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            horizon_days=horizon_days,
            config=DEFAULT_CONFIG,
        )
    )
    return {
        "analysis_date": result["analysis_date"],
        "horizon_days": result["horizon_days"],
        "history_start": result["history_start"],
        "history_end": result["history_end"],
        "method": result["method"],
        "forecast_status": result["forecast_status"],
        "counts": result["counts"],
        **_page(result["items"], limit, offset),
    }


@router.get("/forecast-summary")
def forecast_summary(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    horizon_days: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
) -> dict:
    """Aggregate demand outlook used by the dashboard's Demand Outlook section."""
    horizon_days = _validate_horizon(horizon_days)
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id, product_id)
    return _run(
        lambda: analytics_engine.forecast_summary(
            db_path=DATABASE_PATH,
            store_id=store_id,
            product_id=product_id,
            as_of_date=as_of_date,
            horizon_days=horizon_days,
            config=DEFAULT_CONFIG,
        )
    )


EXECUTIVE_DEFAULT_LIMIT = DEFAULT_CONFIG.executive_default_limit
EXECUTIVE_MAX_LIMIT = DEFAULT_CONFIG.executive_max_limit


@router.get("/executive-summary")
def executive_summary(
    store_id: Optional[int] = Query(None),
    as_of_date: Optional[date] = Query(None),
    limit: int = Query(EXECUTIVE_DEFAULT_LIMIT),
) -> dict:
    """Executive intelligence: health score, counts, top issues and signals.

    Every number is produced deterministically by the analytics engine; the
    endpoint only packages evidence already computed by the existing analytics.
    """
    as_of_date = _validate_analysis_date(as_of_date)
    _validate_references(store_id=store_id)
    if limit < 1 or limit > EXECUTIVE_MAX_LIMIT:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_limit",
                "message": f"limit must be between 1 and {EXECUTIVE_MAX_LIMIT}",
            },
        )
    return _run(
        lambda: analytics_engine.executive(
            db_path=DATABASE_PATH,
            store_id=store_id,
            as_of_date=as_of_date,
            limit=limit,
            config=DEFAULT_CONFIG,
        )
    )