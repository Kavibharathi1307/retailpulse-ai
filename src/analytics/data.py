"""Read-only aggregation of raw retail data for the analytics engine.

All SQL lives here so the calculation modules stay pure and independently
testable. Functions return plain dicts/lists keyed by store/product/date.
"""

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from src.config import DATABASE_PATH
from src.database import connect


def resolve_analysis_date(
    as_of_date: Optional[date] = None, db_path: Path = DATABASE_PATH
) -> date:
    """Return the default analysis date: the latest sale date in the dataset.

    The real-world "today" is never used as the default because the committed
    demo dataset covers a fixed historical range.
    """
    if as_of_date is not None:
        return as_of_date
    with connect(db_path) as conn:
        row = conn.execute("SELECT MAX(sale_date) AS last FROM sales").fetchone()
    if row and row["last"]:
        return date.fromisoformat(row["last"])
    return date.today()


def dataset_date_range(db_path: Path = DATABASE_PATH) -> Optional[tuple[date, date]]:
    """Return (first_date, last_date) of sales history, or None if empty."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT MIN(sale_date) AS a, MAX(sale_date) AS b FROM sales"
        ).fetchone()
    if not row or not row["a"]:
        return None
    return date.fromisoformat(row["a"]), date.fromisoformat(row["b"])


def load_stores(db_path: Path = DATABASE_PATH) -> dict[int, dict]:
    """Map store_id -> store row (store_id, store_name, city, region, active)."""
    with connect(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT store_id, store_name, city, region, active FROM stores ORDER BY store_id"
            ).fetchall()
        ]
    return {r["store_id"]: r for r in rows}


def load_products(db_path: Path = DATABASE_PATH) -> dict[int, dict]:
    """Map product_id -> product row (product_id, product_name, category, unit_price, active)."""
    with connect(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT product_id, product_name, category, unit_price, active"
                " FROM products ORDER BY product_id"
            ).fetchall()
        ]
    return {r["product_id"]: r for r in rows}


def load_inventory(
    db_path: Path = DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
) -> list[dict]:
    """Return current inventory rows joined with store/product names."""
    where, params = [], []
    if store_id is not None:
        where.append("i.store_id = ?")
        params.append(store_id)
    if product_id is not None:
        where.append("i.product_id = ?")
        params.append(product_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with connect(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT i.store_id, st.store_name, i.product_id, p.product_name,"
                " i.current_stock, i.reorder_level"
                f" FROM inventory i"
                f" JOIN stores st ON st.store_id = i.store_id"
                f" JOIN products p ON p.product_id = i.product_id"
                f" {where_sql} ORDER BY i.store_id, i.product_id",
                params,
            ).fetchall()
        ]
    return rows


def load_sales_by_day(
    db_path: Path = DATABASE_PATH,
    start: Optional[date] = None,
    end: Optional[date] = None,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
) -> dict[tuple[int, int], dict[date, dict]]:
    """Return aggregated daily sales keyed by (store_id, product_id).

    Each value maps a date to {"units": int, "revenue": float}. Daily rows are
    summed in case the raw sales table ever contains multiple rows per
    store/product/date.
    """
    aggregated: dict[tuple[int, int], dict[date, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"units": 0, "revenue": 0.0})
    )
    where, params = [], []
    if start is not None:
        where.append("sale_date >= ?")
        params.append(start.isoformat())
    if end is not None:
        where.append("sale_date <= ?")
        params.append(end.isoformat())
    if store_id is not None:
        where.append("store_id = ?")
        params.append(store_id)
    if product_id is not None:
        where.append("product_id = ?")
        params.append(product_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT sale_date, store_id, product_id,"
            f" SUM(quantity_sold) AS units, SUM(revenue) AS revenue"
            f" FROM sales {where_sql}"
            f" GROUP BY sale_date, store_id, product_id",
            params,
        ).fetchall()
    for row in rows:
        key = (row["store_id"], row["product_id"])
        aggregated[key][date.fromisoformat(row["sale_date"])] = {
            "units": row["units"],
            "revenue": row["revenue"],
        }
    return dict(aggregated)