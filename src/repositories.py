"""Repository functions over the retail SQLite database (Milestone 2).

These functions ONLY read raw data and expose filters/pagination. They contain
no analytics -- the analytics layer in a later milestone must compute its own
conclusions from these raw numbers.
"""

from pathlib import Path
from typing import Optional

from src.config import DATABASE_PATH
from src.database import connect


def _rows(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

def get_stores(
    db_path: Path = DATABASE_PATH,
    store_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    with connect(db_path) as conn:
        where, params = [], []
        if store_id is not None:
            where.append("store_id = ?")
            params.append(store_id)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM stores {where_sql}", params
        ).fetchone()[0]
        rows = _rows(
            conn.execute(
                f"SELECT store_id, store_name, city, region, active FROM stores {where_sql}"
                " ORDER BY store_id LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
        )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def store_exists(store_id: int, db_path: Path = DATABASE_PATH) -> bool:
    with connect(db_path) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM stores WHERE store_id = ?", (store_id,)
            ).fetchone()
            is not None
        )


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

def get_products(
    db_path: Path = DATABASE_PATH,
    product_id: Optional[int] = None,
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    with connect(db_path) as conn:
        where, params = [], []
        if product_id is not None:
            where.append("product_id = ?")
            params.append(product_id)
        if category is not None:
            where.append("category = ?")
            params.append(category)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM products {where_sql}", params
        ).fetchone()[0]
        rows = _rows(
            conn.execute(
                f"SELECT product_id, product_name, category, unit_price, active"
                f" FROM products {where_sql} ORDER BY product_id LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
        )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def product_exists(product_id: int, db_path: Path = DATABASE_PATH) -> bool:
    with connect(db_path) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM products WHERE product_id = ?", (product_id,)
            ).fetchone()
            is not None
        )


def get_categories(db_path: Path = DATABASE_PATH) -> list[str]:
    with connect(db_path) as conn:
        return [
            str(row["category"])
            for row in conn.execute(
                "SELECT DISTINCT category FROM products ORDER BY category"
            ).fetchall()
        ]


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

def get_sales(
    db_path: Path = DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    with connect(db_path) as conn:
        where, params = [], []
        if store_id is not None:
            where.append("s.store_id = ?")
            params.append(store_id)
        if product_id is not None:
            where.append("s.product_id = ?")
            params.append(product_id)
        if start_date is not None:
            where.append("s.sale_date >= ?")
            params.append(start_date)
        if end_date is not None:
            where.append("s.sale_date <= ?")
            params.append(end_date)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM sales s {where_sql}", params
        ).fetchone()[0]
        rows = _rows(
            conn.execute(
                f"SELECT s.sale_id, s.sale_date, s.store_id, st.store_name,"
                f" s.product_id, p.product_name, s.quantity_sold, s.revenue"
                f" FROM sales s"
                f" JOIN stores st ON st.store_id = s.store_id"
                f" JOIN products p ON p.product_id = s.product_id"
                f" {where_sql} ORDER BY s.sale_date DESC, s.sale_id DESC"
                f" LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
        )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def get_sales_date_range(db_path: Path = DATABASE_PATH) -> Optional[dict]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT MIN(sale_date) AS first_date, MAX(sale_date) AS last_date FROM sales"
        ).fetchone()
    if row["first_date"] is None:
        return None
    return {"first_date": row["first_date"], "last_date": row["last_date"]}


def get_sales_series(
    db_path: Path = DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
) -> dict:
    """Daily sales totals (units + revenue) for trend charts and KPIs.

    Aggregates the raw daily transaction history into one row per day so the
    frontend can render a revenue/units chart and headline numbers without
    pulling thousands of individual sale records.
    """
    with connect(db_path) as conn:
        where, params = [], []
        if store_id is not None:
            where.append("s.store_id = ?")
            params.append(store_id)
        if product_id is not None:
            where.append("s.product_id = ?")
            params.append(product_id)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = _rows(
            conn.execute(
                f"SELECT s.sale_date, SUM(s.quantity_sold) AS units,"
                f" SUM(s.revenue) AS revenue FROM sales s {where_sql}"
                f" GROUP BY s.sale_date ORDER BY s.sale_date",
                params,
            )
        )
    return {
        "items": rows,
        "start_date": rows[0]["sale_date"] if rows else None,
        "end_date": rows[-1]["sale_date"] if rows else None,
    }


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def get_inventory(
    db_path: Path = DATABASE_PATH,
    store_id: Optional[int] = None,
    product_id: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    with connect(db_path) as conn:
        where, params = [], []
        if store_id is not None:
            where.append("i.store_id = ?")
            params.append(store_id)
        if product_id is not None:
            where.append("i.product_id = ?")
            params.append(product_id)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM inventory i {where_sql}", params
        ).fetchone()[0]
        rows = _rows(
            conn.execute(
                f"SELECT i.inventory_id, i.store_id, st.store_name, i.product_id,"
                f" p.product_name, i.current_stock, i.reorder_level,"
                f" i.last_restock_date"
                f" FROM inventory i"
                f" JOIN stores st ON st.store_id = i.store_id"
                f" JOIN products p ON p.product_id = i.product_id"
                f" {where_sql} ORDER BY i.store_id, i.product_id"
                f" LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
        )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def get_data_summary(db_path: Path = DATABASE_PATH) -> dict:
    with connect(db_path) as conn:
        counts = {
            "stores": conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0],
            "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "sales": conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
            "inventory": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
        }
    summary = {"counts": counts}
    date_range = get_sales_date_range(db_path)
    if date_range:
        summary.update(date_range)
    return summary