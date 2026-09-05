"""SQLite schema for the RetailPulse retail data layer (Milestone 2).

The schema intentionally stores *raw* retail data only. No computed analytical
conclusions (stock-out risk, overstock, trends) live here -- the analytics layer
in a later milestone must derive those from these raw numbers.
"""

SCHEMA_NAME = "retailpulse"
SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stores (
    store_id    INTEGER PRIMARY KEY,
    store_name  TEXT NOT NULL,
    city        TEXT NOT NULL,
    region      TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS products (
    product_id   INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category     TEXT NOT NULL,
    unit_price   REAL NOT NULL CHECK (unit_price >= 0),
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_date      TEXT NOT NULL,
    store_id       INTEGER NOT NULL REFERENCES stores (store_id),
    product_id     INTEGER NOT NULL REFERENCES products (product_id),
    quantity_sold  INTEGER NOT NULL CHECK (quantity_sold >= 0),
    revenue        REAL NOT NULL CHECK (revenue >= 0)
);

CREATE INDEX IF NOT EXISTS idx_sales_date    ON sales (sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_store   ON sales (store_id);
CREATE INDEX IF NOT EXISTS idx_sales_product ON sales (product_id);

CREATE TABLE IF NOT EXISTS inventory (
    inventory_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id          INTEGER NOT NULL REFERENCES stores (store_id),
    product_id        INTEGER NOT NULL REFERENCES products (product_id),
    current_stock     INTEGER NOT NULL CHECK (current_stock >= 0),
    reorder_level     INTEGER NOT NULL CHECK (reorder_level >= 0),
    last_restock_date TEXT NOT NULL,
    UNIQUE (store_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_store   ON inventory (store_id);
CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory (product_id);
"""


def apply_schema(conn) -> None:
    """Apply the (idempotent) schema to the given SQLite connection."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()