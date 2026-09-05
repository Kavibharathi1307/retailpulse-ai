"""JSON API endpoints for the retail data layer (Milestone 2).

Each endpoint returns structured JSON with pagination info, supports optional
filters, and fails gracefully with useful HTTP status codes. No analytics or AI
lives here -- only access to the raw retail dataset.
"""

from datetime import date
from typing import Optional

import sqlite3
from fastapi import APIRouter, HTTPException, Query

from src import repositories

router = APIRouter(prefix="/api", tags=["data"])

DEFAULT_SALES_LIMIT = 100
MAX_SALES_LIMIT = 1000


def _bounded_limit(limit: int, maximum: int, label: str) -> int:
    if limit < 0 or limit > maximum:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_limit", "message": f"{label} must be between 0 and {maximum}"},
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


def _run(operation) -> dict:
    try:
        return operation()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "The retail database is currently unavailable.",
            },
        ) from exc


@router.get("/stores")
def get_stores(
    store_id: Optional[int] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit, 200, "limit")
    offset = _offset(offset)
    if store_id is not None and not repositories.store_exists(store_id=store_id):
        _require_resource(False, "store", store_id)
    return _run(lambda: repositories.get_stores(store_id=store_id, limit=limit, offset=offset))


@router.get("/products")
def get_products(
    product_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit, 200, "limit")
    offset = _offset(offset)
    if product_id is not None and not repositories.product_exists(product_id=product_id):
        _require_resource(False, "product", product_id)
    return _run(
        lambda: repositories.get_products(
            product_id=product_id, category=category, limit=limit, offset=offset
        )
    )


@router.get("/sales")
def get_sales(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(DEFAULT_SALES_LIMIT),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit, MAX_SALES_LIMIT, "limit")
    offset = _offset(offset)
    if store_id is not None and not repositories.store_exists(store_id=store_id):
        _require_resource(False, "store", store_id)
    if product_id is not None and not repositories.product_exists(product_id=product_id):
        _require_resource(False, "product", product_id)
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_range", "message": "start_date must not be after end_date"},
        )
    return _run(
        lambda: repositories.get_sales(
            store_id=store_id,
            product_id=product_id,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat() if end_date else None,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/inventory")
def get_inventory(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    limit: int = Query(200),
    offset: int = Query(0),
) -> dict:
    limit = _bounded_limit(limit, 500, "limit")
    offset = _offset(offset)
    if store_id is not None and not repositories.store_exists(store_id=store_id):
        _require_resource(False, "store", store_id)
    if product_id is not None and not repositories.product_exists(product_id=product_id):
        _require_resource(False, "product", product_id)
    return _run(
        lambda: repositories.get_inventory(
            store_id=store_id, product_id=product_id, limit=limit, offset=offset
        )
    )


@router.get("/data/summary")
def data_summary() -> dict:
    return _run(repositories.get_data_summary)


@router.get("/data/sales-series")
def sales_series() -> dict:
    """Daily units + revenue totals across the full sales history (for charts)."""
    return _run(repositories.get_sales_series)