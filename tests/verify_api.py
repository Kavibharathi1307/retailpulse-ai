"""HTTP-level verification of the Milestone 2 data APIs.

Starts the real application (as ``python app.py`` would) in a background thread
and exercises every data endpoint over actual HTTP with the standard library.

Run from the project root:

    python tests/verify_api.py
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import app

BASE_URL = "http://127.0.0.1:8000"
FAILURES = []


def get(path: str):
    with urllib.request.urlopen(BASE_URL + path, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def get_raw(path: str):
    with urllib.request.urlopen(BASE_URL + path, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")


def expect_status(path: str, expected: int) -> None:
    try:
        status, _ = get(path)
        if status != expected:
            FAILURES.append(f"{path}: expected {expected}, got {status}")
    except urllib.error.HTTPError as exc:
        if exc.code != expected:
            FAILURES.append(f"{path}: expected {expected}, got HTTP {exc.code}")


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{label} {detail}")


def main() -> int:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(60):
        try:
            status, _ = get("/api/health")
            if status == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print("FAIL server did not become ready")
        return 1

    status, health = get("/api/health")
    check("GET /api/health returns ok", status == 200 and health.get("status") == "ok")

    status, html = get_raw("/")
    check("GET / serves the frontend", status == 200)
    check("frontend includes data-status section", 'id="data-stores"' in html)

    status, stores = get("/api/stores")
    check("GET /api/stores works", status == 200 and stores["total"] == 5)
    check("store row has required fields",
          all(k in stores["items"][0] for k in ("store_id", "store_name", "city", "region", "active")))

    status, products = get("/api/products")
    check("GET /api/products works", status == 200 and 25 <= products["total"] <= 50)
    check("product row has required fields",
          all(k in products["items"][0] for k in ("product_id", "product_name", "category", "unit_price", "active")))
    check("product prices non-negative", all(p["unit_price"] >= 0 for p in products["items"]))

    status, sales = get("/api/sales?limit=100")
    check("GET /api/sales works", status == 200 and sales["total"] > 0 and len(sales["items"]) == 100)
    check("sales row has required fields",
          all(k in sales["items"][0] for k in ("sale_id", "sale_date", "store_id", "product_id", "quantity_sold", "revenue")))
    check("sales quantities non-negative", all(s["quantity_sold"] >= 0 for s in sales["items"]))
    check("sales revenue non-negative", all(s["revenue"] >= 0 for s in sales["items"]))

    status, inventory = get("/api/inventory")
    check("GET /api/inventory works", status == 200 and inventory["total"] == 180)
    check("inventory row has required fields",
          all(k in inventory["items"][0] for k in ("inventory_id", "store_id", "product_id", "current_stock", "reorder_level", "last_restock_date")))
    check("inventory stock non-negative",
          all(i["current_stock"] >= 0 and i["reorder_level"] >= 0 for i in inventory["items"]))

    status, summary = get("/api/data/summary")
    check("GET /api/data/summary works",
          status == 200 and summary["counts"] == {"stores": 5, "products": 36, "inventory": 180, "sales": 14450})

    # Filtered queries
    status, s1 = get("/api/sales?store_id=1&limit=100")
    check("sales filtered by store_id", status == 200 and all(s["store_id"] == 1 for s in s1["items"]) and s1["total"] > 0)
    status, s2 = get("/api/sales?product_id=7&limit=100")
    check("sales filtered by product_id", status == 200 and all(s["product_id"] == 7 for s in s2["items"]) and s2["total"] > 0)
    status, s3 = get("/api/sales?start_date=2026-01-01&end_date=2026-01-31&limit=100")
    check("sales filtered by date range", status == 200 and all("2026-01-01" <= s["sale_date"] <= "2026-01-31" for s in s3["items"]))
    status, inv = get("/api/inventory?store_id=2")
    check("inventory filtered by store", status == 200 and inv["total"] == 36 and all(i["store_id"] == 2 for i in inv["items"]))
    status, invp = get("/api/inventory?product_id=34")
    check("inventory filtered by product", status == 200 and all(i["product_id"] == 34 for i in invp["items"]))
    status, cat = get("/api/products?category=Snacks")
    check("products filtered by category", status == 200 and all(p["category"] == "Snacks" for p in cat["items"]))

    # Error handling
    expect_status("/api/stores?store_id=999", 404)
    expect_status("/api/products?product_id=999", 404)
    expect_status("/api/sales?store_id=999", 404)
    expect_status("/api/inventory?product_id=999", 404)
    expect_status("/api/sales?start_date=not-a-date", 422)
    expect_status("/api/sales?start_date=2026-02-01&end_date=2026-01-01", 400)
    expect_status("/api/sales?limit=5000", 400)
    expect_status("/api/inventory?offset=-1", 400)

    server.should_exit = True
    thread.join(timeout=10)

    if FAILURES:
        print("\nFailures:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nAll API checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())