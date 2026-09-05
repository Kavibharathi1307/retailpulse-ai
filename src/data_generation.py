"""Deterministic retail sample-data generator (Milestone 2).

Running this module reproduces exactly the same dataset every time:

* fixed random seed
* fixed store / product catalog
* fixed date range (no dependence on the current time)
* sales derived from a fixed per-product demand model

Revenue is always stored as ``quantity_sold * product.unit_price`` so the two
can never contradict each other.

The catalog intentionally embeds raw behavioural patterns (fast movers, slow
movers, a seasonal product, a declining product, a short spike, a short drop,
low-stock and overstock inventory) -- WITHOUT labelling any of it. The analytics
layer in a later milestone must recover those patterns from the raw numbers.
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from src.schema import apply_schema

FIXED_SEED = 20240424
HISTORY_DAYS = 90
END_DATE = date(2026, 1, 31)
START_DATE = END_DATE - timedelta(days=HISTORY_DAYS - 1)

LOW_STOCK_PRODUCT_IDS = {1, 7, 29}   # fast movers deliberately running thin
OVERSTOCK_PRODUCT_IDS = {17, 24, 33, 34}  # slow movers deliberately overstocked

STORES = [
    {"store_id": 1, "store_name": "Downtown Store", "city": "Metroville", "region": "Central", "active": 1, "weight": 1.2},
    {"store_id": 2, "store_name": "Central Mall", "city": "Metroville", "region": "Central", "active": 1, "weight": 1.4},
    {"store_id": 3, "store_name": "Riverside Store", "city": "Greenvale", "region": "North", "active": 1, "weight": 0.8},
    {"store_id": 4, "store_name": "Market Street Store", "city": "Lakeside", "region": "South", "active": 1, "weight": 1.0},
    {"store_id": 5, "store_name": "Harbor Plaza", "city": "Bayport", "region": "East", "active": 1, "weight": 0.9},
]

# (product_id, product_name, category, unit_price, pattern, profile)
# base = typical chain-wide daily units sold (all stores combined).
PRODUCTS = [
    (1, "Spring Water 1L", "Beverages", 25.0, "fast", {"base": 16.0}),
    (2, "Citrus Orange Juice 1L", "Beverages", 95.0, "normal", {"base": 5.0}),
    (3, "Classic Cola 500ml", "Beverages", 40.0, "declining", {"base": 5.5, "start": 1.35, "end": 0.3}),
    (4, "Cold Brew Coffee 250ml", "Beverages", 120.0, "normal", {"base": 2.5}),
    (5, "Green Tea Pack 25 bags", "Beverages", 150.0, "drop", {"base": 4.0, "start": date(2026, 1, 5), "end": date(2026, 1, 14), "factor": 0.1}),
    (6, "Mango Smoothie 250ml", "Beverages", 60.0, "normal", {"base": 2.0}),
    (7, "Salted Potato Chips 90g", "Snacks", 20.0, "fast", {"base": 18.0}),
    (8, "Chocolate Cookies 200g", "Snacks", 65.0, "normal", {"base": 6.0}),
    (9, "Trail Mix 150g", "Snacks", 130.0, "normal", {"base": 3.0}),
    (10, "Cheese Crackers 100g", "Snacks", 45.0, "normal", {"base": 4.0}),
    (11, "Peanut Butter 350g", "Snacks", 165.0, "normal", {"base": 2.0}),
    (12, "Chocolate Bar 40g", "Snacks", 30.0, "seasonal", {"base": 3.5, "start": date(2025, 12, 14), "end": date(2025, 12, 31), "factor": 3.0}),
    (13, "Shampoo 200ml", "Personal Care", 210.0, "normal", {"base": 2.5}),
    (14, "Toothpaste 150g", "Personal Care", 85.0, "normal", {"base": 4.0}),
    (15, "Bath Soap 100g", "Personal Care", 35.0, "normal", {"base": 7.0}),
    (16, "Hand Sanitizer 100ml", "Personal Care", 55.0, "spike", {"base": 1.8, "start": date(2025, 12, 8), "end": date(2025, 12, 12), "factor": 5.0}),
    (17, "Body Lotion 250ml", "Personal Care", 175.0, "slow", {"base": 0.6}),
    (18, "Face Wash 100ml", "Personal Care", 140.0, "normal", {"base": 1.8}),
    (19, "Dish Soap 500ml", "Household", 110.0, "normal", {"base": 3.5}),
    (20, "Laundry Detergent 1kg", "Household", 240.0, "normal", {"base": 2.0}),
    (21, "Glass Cleaner 500ml", "Household", 90.0, "normal", {"base": 2.2}),
    (22, "Garbage Bags 30s", "Household", 70.0, "normal", {"base": 3.0}),
    (23, "Paper Towels 2 rolls", "Household", 55.0, "normal", {"base": 3.5}),
    (24, "Storage Container Set", "Household", 190.0, "slow", {"base": 0.5}),
    (25, "Basmati Rice 5kg", "Grocery", 320.0, "normal", {"base": 1.8}),
    (26, "Wheat Flour 2kg", "Grocery", 95.0, "normal", {"base": 3.0}),
    (27, "Sunflower Oil 1L", "Grocery", 145.0, "normal", {"base": 2.5}),
    (28, "Tomato Ketchup 500g", "Grocery", 75.0, "normal", {"base": 3.5}),
    (29, "Instant Noodles 6-pack", "Grocery", 66.0, "fast", {"base": 12.0}),
    (30, "Sugar 1kg", "Grocery", 48.0, "normal", {"base": 2.5}),
    (31, "USB Cable 1m", "Electronics Accessories", 150.0, "normal", {"base": 1.2}),
    (32, "Phone Charger 20W", "Electronics Accessories", 349.0, "normal", {"base": 0.8}),
    (33, "Wireless Mouse", "Electronics Accessories", 449.0, "slow", {"base": 0.25}),
    (34, "Bluetooth Earbuds", "Electronics Accessories", 899.0, "slow", {"base": 0.2}),
    (35, "HDMI Cable 2m", "Electronics Accessories", 199.0, "normal", {"base": 0.6}),
    (36, "Power Bank 10000mAh", "Electronics Accessories", 799.0, "normal", {"base": 0.4}),
]


def _pattern_multiplier(pattern: str, profile: dict, day: date) -> float:
    """Return the demand multiplier for a product pattern on a given day."""
    if pattern == "declining":
        span = (END_DATE - START_DATE).days or 1
        progress = (day - START_DATE).days / span
        return profile["start"] + (profile["end"] - profile["start"]) * progress
    if pattern in ("seasonal", "spike", "drop"):
        start, end = profile["start"], profile["end"]
        if start <= day <= end:
            return profile["factor"]
        return 1.0
    return 1.0


def _sales_multiplier(weight: float, day: date) -> float:
    """Weekend/weekday cadence so daily sales oscillate realistically."""
    if day.weekday() >= 5:  # Saturday / Sunday
        return 1.35 * weight
    return weight


def _day_steps() -> Iterable[date]:
    current = START_DATE
    while current <= END_DATE:
        yield current
        current += timedelta(days=1)


def generate_dataset(db_path: Path, force: bool = False) -> dict:
    """Generate the full retail dataset into an SQLite database.

    If ``force`` is False and the target database already contains sales data,
    it is left untouched and the current counts are returned instead.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        apply_schema(conn)

        if not force and conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] > 0:
            counts = {
                "stores": conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0],
                "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                "sales": conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
                "inventory": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
            }
            return counts

        rng = random.Random(FIXED_SEED)

        conn.execute("DELETE FROM sales")
        conn.execute("DELETE FROM inventory")
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM stores")

        for store in STORES:
            conn.execute(
                "INSERT INTO stores (store_id, store_name, city, region, active) VALUES (?, ?, ?, ?, ?)",
                (store["store_id"], store["store_name"], store["city"], store["region"], store["active"]),
            )

        for product in PRODUCTS:
            product_id, name, category, price, pattern, profile = product
            conn.execute(
                "INSERT INTO products (product_id, product_name, category, unit_price, active) VALUES (?, ?, ?, ?, 1)",
                (product_id, name, category, price),
            )

        store_weight = {s["store_id"]: s["weight"] for s in STORES}

        sale_rows = []
        for product in PRODUCTS:
            product_id, _, _, price, pattern, profile = product
            base = profile["base"]
            for store_id, weight in store_weight.items():
                sigmas = max(base * weight * 0.4, 0.3)
                for day in _day_steps():
                    multiplier = _pattern_multiplier(pattern, profile, day) * _sales_multiplier(
                        weight, day
                    )
                    mean = max(base * multiplier, 0.0)
                    qty = int(round(rng.gauss(mean, sigmas)))
                    if qty < 0:
                        qty = 0
                    if qty == 0:
                        continue
                    revenue = round(qty * price, 2)
                    sale_rows.append((day.isoformat(), store_id, product_id, qty, revenue))

        conn.executemany(
            "INSERT INTO sales (sale_date, store_id, product_id, quantity_sold, revenue) VALUES (?, ?, ?, ?, ?)",
            sale_rows,
        )

        inventory_rows = []
        for store in STORES:
            store_id = store["store_id"]
            weight = store["weight"]
            for product in PRODUCTS:
                product_id, _, _, _, _, profile = product
                base = profile["base"]
                daily_units = max(base * weight, 0.0)
                if product_id in LOW_STOCK_PRODUCT_IDS:
                    buffer_days = rng.randint(4, 6)
                    reorder_level = max(int(round(daily_units * buffer_days)), 1)
                    stock_cover = reorder_level * rng.uniform(0.55, 0.9)
                    current_stock = max(int(round(stock_cover)), 0)
                elif product_id in OVERSTOCK_PRODUCT_IDS:
                    buffer_days = rng.randint(20, 28)
                    reorder_level = max(int(round(daily_units * buffer_days)), 1)
                    overstock_days = rng.randint(60, 120)
                    current_stock = max(
                        int(round(daily_units * overstock_days)), reorder_level * 4
                    )
                else:
                    buffer_days = rng.randint(5, 8)
                    reorder_level = max(int(round(daily_units * buffer_days)), 1)
                    stock_days = rng.randint(10, 30)
                    current_stock = max(int(round(daily_units * stock_days)), reorder_level + 1)
                last_restock = (END_DATE - timedelta(days=rng.randint(1, 14))).isoformat()
                inventory_rows.append(
                    (store_id, product_id, current_stock, reorder_level, last_restock)
                )

        conn.executemany(
            "INSERT INTO inventory (store_id, product_id, current_stock, reorder_level, last_restock_date)"
            " VALUES (?, ?, ?, ?, ?)",
            inventory_rows,
        )

        conn.commit()
    finally:
        conn.close()

    return _counts(db_path)


def _counts(db_path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return {
            "stores": conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0],
            "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "sales": conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
            "inventory": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
        }
    finally:
        conn.close()


def main() -> None:
    """Regenerate the committed sample database from the project root."""
    from src.config import DATABASE_PATH

    counts = generate_dataset(DATABASE_PATH, force=True)
    print(f"Regenerated {DATABASE_PATH}")
    print(
        "stores={stores} products={products} sales={sales} inventory={inventory}".format(**counts)
    )


if __name__ == "__main__":
    main()