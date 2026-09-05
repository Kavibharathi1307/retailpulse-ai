"""Data-quality verification for the committed retail dataset (Milestone 2).

Runs the Milestone 2 quality checks against ``data/retailpulse.db`` and exits
with status 0 only when every check passes:

  1. every sale references an existing store
  2. every sale references an existing product
  3. every inventory record references an existing store
  4. every inventory record references an existing product
  5. every revenue equals quantity_sold * product.unit_price
  6. no negative inventory
  7. no negative sales quantities
  8. no invalid dates
  9. every store has products/inventory where expected
 10. the dataset has enough history for future analytics
 11. the intended fast/slow mover, low/high stock patterns exist in raw numbers

Usage (from the project root):

    python data/verify_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3  # noqa: E402

from src.config import DATABASE_PATH  # noqa: E402
from src.datavalidation import (  # noqa: E402
    validate_inventory,
    validate_product,
    validate_sale,
    validate_store,
)


class Check:
    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []

    def ok(self) -> bool:
        return not self.errors

    def report(self) -> str:
        mark = "PASS" if self.ok() else "FAIL"
        line = f"[{mark}] {self.name}"
        if not self.ok():
            line += " -- " + "; ".join(self.errors[:3])
        return line


def fetch_all(conn, sql: str, params=()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def data_quality_checks(conn) -> list[Check]:
    store_ids = {r["store_id"] for r in fetch_all(conn, "SELECT store_id FROM stores")}
    product_ids = {r["product_id"] for r in fetch_all(conn, "SELECT product_id FROM products")}
    products = {r["product_id"]: r for r in fetch_all(conn, "SELECT * FROM products")}
    stores = fetch_all(conn, "SELECT * FROM stores")

    checks = []

    # 1 & 2 -- foreign keys on sales
    sale_fk = Check("sales reference existing stores and products")
    for row in fetch_all(conn, "SELECT store_id, product_id FROM sales LIMIT 100000"):
        problems = []
        if row["store_id"] not in store_ids:
            problems.append(f"store {row['store_id']}")
        if row["product_id"] not in product_ids:
            problems.append(f"product {row['product_id']}")
        if problems:
            sale_fk.errors.append(", ".join(problems))
    checks.append(sale_fk)

    # 3 & 4 -- foreign keys on inventory
    inv_fk = Check("inventory references existing stores and products")
    for row in fetch_all(conn, "SELECT store_id, product_id FROM inventory"):
        problems = []
        if row["store_id"] not in store_ids:
            problems.append(f"store {row['store_id']}")
        if row["product_id"] not in product_ids:
            problems.append(f"product {row['product_id']}")
        if problems:
            inv_fk.errors.append(", ".join(problems))
    checks.append(inv_fk)

    # 5 -- revenue consistency
    revenue = Check("revenue equals quantity_sold * unit_price")
    bad = 0
    for row in fetch_all(conn, "SELECT * FROM sales LIMIT 100000"):
        expected = round(row["quantity_sold"] * products[row["product_id"]]["unit_price"], 2)
        if abs(float(row["revenue"]) - expected) > 0.001:
            bad += 1
            if bad <= 3:
                revenue.errors.append(f"sale {row['sale_id']}: {row['revenue']} != {expected}")
    if bad:
        revenue.errors.append(f"{bad} sales rows disagree with unit price")
    checks.append(revenue)

    # 6 -- no negative inventory
    neg_inv = Check("no negative inventory")
    for key in ("current_stock", "reorder_level"):
        n = conn.execute(f"SELECT COUNT(*) FROM inventory WHERE {key} < 0").fetchone()[0]
        if n:
            neg_inv.errors.append(f"{n} rows with negative {key}")
    checks.append(neg_inv)

    # 7 -- no negative sales quantities
    neg_sales = Check("no negative sales quantities")
    n = conn.execute("SELECT COUNT(*) FROM sales WHERE quantity_sold < 0").fetchone()[0]
    if n:
        neg_sales.errors.append(f"{n} rows with negative quantity_sold")
    checks.append(neg_sales)

    # 8 -- no invalid dates
    dates = Check("no invalid dates")
    bad_dates = 0
    for row in fetch_all(
        conn,
        "SELECT sale_id, sale_date FROM sales UNION ALL SELECT inventory_id, last_restock_date FROM inventory",
    ):
        try:
            ints = str(row.get("sale_date", row.get("last_restock_date"))).split("-")
            if len(ints) != 3:
                raise ValueError
            y, m, d = (int(v) for v in ints)
            if not (1 <= m <= 12) or not (1 <= d <= 31):
                raise ValueError
        except (ValueError, TypeError):
            bad_dates += 1
            if bad_dates <= 3:
                dates.errors.append(str(row))
    if bad_dates:
        dates.errors.append(f"{bad_dates} malformed dates")
    checks.append(dates)

    # 9 -- every store has inventory (and sales) where expected
    store_coverage = Check("every store has sales and inventory records")
    for store in stores:
        inv_count = conn.execute(
            "SELECT COUNT(*) FROM inventory WHERE store_id = ?", (store["store_id"],)
        ).fetchone()[0]
        sale_count = conn.execute(
            "SELECT COUNT(*) FROM sales WHERE store_id = ?", (store["store_id"],)
        ).fetchone()[0]
        if inv_count == 0:
            store_coverage.errors.append(f"store {store['store_id']} has no inventory")
        if sale_count == 0:
            store_coverage.errors.append(f"store {store['store_id']} has no sales")
    checks.append(store_coverage)

    # 10 -- enough history for future analytics
    history = Check("dataset has enough history for future analytics")
    from datetime import date as _date, timedelta as _td  # noqa: F401

    min_max = conn.execute(
        "SELECT MIN(sale_date) AS first_date, MAX(sale_date) AS last_date FROM sales"
    ).fetchone()
    if not min_max or not min_max["first_date"]:
        history.errors.append("no sales history present")
    else:
        span_days = (
            _date.fromisoformat(min_max["last_date"])
            - _date.fromisoformat(min_max["first_date"])
        ).days + 1
        if span_days < 60:
            history.errors.append(f"only {span_days} days of history")
    checks.append(history)

    # 11 -- intended patterns exist in the raw numbers
    patterns = Check("fast/slow mover and low/high stock patterns exist in raw data")
    _raw_patterns(conn, patterns)
    checks.append(patterns)

    return checks


def _raw_patterns(conn, check: Check) -> None:
    """Verify that the intended behavioural patterns are visible in raw numbers."""
    from src.data_generation import LOW_STOCK_PRODUCT_IDS, OVERSTOCK_PRODUCT_IDS

    conn.row_factory = sqlite3.Row

    # Average daily units sold chain-wide per product (last 60 days).
    avg = {}
    for r in conn.execute(
        "SELECT product_id, SUM(quantity_sold) / 60.0 AS daily FROM sales"
        " WHERE sale_date > ? GROUP BY product_id",
        ("2025-12-03",),
    ):
        avg[r["product_id"]] = r["daily"]

    # Fast vs slow movers (products 7 & 34 are fixed anchors in the catalog).
    if avg.get(7, 0) < 8:
        check.errors.append("fast mover (Salted Potato Chips) not selling fast enough")
    if avg.get(1, 0) < 6:
        check.errors.append("fast mover (Spring Water) not selling fast enough")
    if avg.get(34, 0) > 2:
        check.errors.append("slow mover (Bluetooth Earbuds) not slow enough")

    # Seasonal spike: chocolate bars in the festive window vs outside.
    seasonal = conn.execute(
        "SELECT AVG(q) AS m FROM ("
        " SELECT SUM(quantity_sold) AS q FROM sales WHERE product_id = 12"
        " AND sale_date BETWEEN '2025-12-14' AND '2025-12-31' GROUP BY sale_date"
        ")",
    ).fetchone()["m"]
    baseline = conn.execute(
        "SELECT AVG(q) AS m FROM ("
        " SELECT SUM(quantity_sold) AS q FROM sales WHERE product_id = 12"
        " AND sale_date BETWEEN '2025-11-03' AND '2025-12-13' GROUP BY sale_date"
        ")",
    ).fetchone()["m"]
    if seasonal and baseline and seasonal < baseline * 1.8:
        check.errors.append("seasonal product did not clearly surge during its window")

    # Declining product: first 30 days vs last 30 days.
    early = conn.execute(
        "SELECT SUM(quantity_sold) FROM sales WHERE product_id = 3"
        " AND sale_date BETWEEN '2025-11-03' AND '2025-12-02'",
    ).fetchone()[0] or 0
    late = conn.execute(
        "SELECT SUM(quantity_sold) FROM sales WHERE product_id = 3"
        " AND sale_date BETWEEN '2026-01-02' AND '2026-01-31'",
    ).fetchone()[0] or 0
    if late >= early * 0.7:
        check.errors.append("declining product did not decline clearly")

    # Short spike: hand sanitizer window vs the days right before it.
    spike = conn.execute(
        "SELECT SUM(quantity_sold) FROM sales WHERE product_id = 16"
        " AND sale_date BETWEEN '2025-12-08' AND '2025-12-12'",
    ).fetchone()[0] or 0
    pre_spike = conn.execute(
        "SELECT SUM(quantity_sold) FROM sales WHERE product_id = 16"
        " AND sale_date BETWEEN '2025-12-01' AND '2025-12-07'",
    ).fetchone()[0] or 1
    if spike <= pre_spike * 1.8:
        check.errors.append("short spike did not stand out against its baseline")

    # Short drop: green tea window vs the days before it.
    drop = conn.execute(
        "SELECT SUM(quantity_sold) FROM sales WHERE product_id = 5"
        " AND sale_date BETWEEN '2026-01-05' AND '2026-01-14'",
    ).fetchone()[0] or 0
    pre_drop = conn.execute(
        "SELECT SUM(quantity_sold) FROM sales WHERE product_id = 5"
        " AND sale_date BETWEEN '2025-12-26' AND '2026-01-04'",
    ).fetchone()[0] or 0
    if pre_drop > 0 and drop >= pre_drop * 0.4:
        check.errors.append("short drop did not clearly reduce the product's sales")

    # Low-stock situation: some fast movers sit at or below their reorder level.
    low_rows = conn.execute(
        "SELECT COUNT(*) FROM inventory WHERE product_id IN (1, 7, 29)"
        " AND current_stock <= reorder_level",
    ).fetchone()[0]
    if low_rows < 3:
        check.errors.append("expected low-stock situations for fast movers not found")

    # Overstock situation: slow movers carry far more than a quarter of demand.
    high_rows = conn.execute(
        "SELECT COUNT(*) FROM inventory WHERE product_id IN (17, 24, 33, 34)"
        " AND current_stock > reorder_level * 3",
    ).fetchone()[0]
    if high_rows < 4:
        check.errors.append("expected overstock situations for slow movers not found")


def main() -> int:
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    try:
        if conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0:
            print(f"FAIL dataset not populated: {DATABASE_PATH}")
            return 1
        checks = data_quality_checks(conn)
        all_ok = True
        for check in checks:
            print(check.report())
            all_ok = all_ok and check.ok()
        (counts := {})
        for table in ("stores", "products", "sales", "inventory"):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(
            "Dataset: stores={stores} products={products} sales={sales} inventory={inventory}".format(
                **counts
            )
        )
        return 0 if all_ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())