"""HTTP-level verification of the Milestone 3 analytics APIs.

Starts the real application in a background thread and exercises every
/analytics endpoint plus regression checks on the data endpoints.

Run from the project root:

    .venv\\Scripts\\python.exe tests\\verify_analytics_api.py
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
    with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{label} {detail}")


def expect_status(path: str, expected: int) -> None:
    try:
        status, _ = get(path)
        if status != expected:
            FAILURES.append(f"{path}: expected {expected}, got {status}")
    except urllib.error.HTTPError as exc:
        if exc.code != expected:
            FAILURES.append(f"{path}: expected {expected}, got HTTP {exc.code}")


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

    # --- attention summary -------------------------------------------------
    status, summary = get("/api/analytics/attention-summary?limit=100")
    check("GET /api/analytics/attention-summary works", status == 200)
    check("attention summary reports analysis_date=2026-01-31",
          summary.get("analysis_date") == "2026-01-31")
    check("attention summary has counts and items",
          "counts" in summary and "items" in summary and "total" in summary)
    check("attention counts total matches item count",
          summary["counts"]["total"] == summary["total"])
    check("attention items carry evidence",
          all("evidence" in item and "explanation" in item for item in summary["items"]))
    issue_types = {item["issue_type"] for item in summary["items"]}
    check("attention has stock-out risks",
          "STOCK_OUT_RISK" in issue_types,
          str(sorted(issue_types)))
    check("attention sorted by severity (CRITICAL first)",
          summary["items"][0]["severity"] == "CRITICAL")

    # --- stock-out risks ---------------------------------------------------
    status, stockout = get("/api/analytics/stock-out-risks?limit=100")
    check("GET /api/analytics/stock-out-risks works",
          status == 200 and stockout["total"] == 180)
    statuses = {row["status"] for row in stockout["items"]}
    check("stock-out items expose status", "CRITICAL" in statuses or "HIGH" in statuses, str(statuses))
    check("stock-out critical row has estimated date",
          any(row["estimated_stock_out_date"] is not None for row in stockout["items"] if row["status"] == "CRITICAL"))

    # --- overstock ---------------------------------------------------------
    status, over = get("/api/analytics/overstock?limit=100")
    check("GET /api/analytics/overstock works", status == 200 and over["total"] == 180)
    check("overstock finds OVERSTOCK items",
          any(row["status"] == "OVERSTOCK" for row in over["items"]))

    # --- slow movers -------------------------------------------------------
    status, slow = get("/api/analytics/slow-movers?limit=100")
    check("GET /api/analytics/slow-movers works", status == 200 and slow["total"] == 180)
    check("slow-movers finds SLOW_MOVER items",
          any(row["status"] == "SLOW_MOVER" for row in slow["items"]))

    # --- sales anomalies ---------------------------------------------------
    status, anomalies = get("/api/analytics/sales-anomalies?limit=100")
    check("GET /api/analytics/sales-anomalies works", status == 200 and anomalies["total"] == 180)
    directions = {row["direction"] for row in anomalies["items"]}
    check("anomalies include SPIKE and DROP",
          "SPIKE" in directions and "DROP" in directions, str(directions))
    spike = next(row for row in anomalies["items"] if row["direction"] == "SPIKE")
    check("spike has evidence windows",
          "recent_window_start" in spike["evidence"] and "baseline_window_start" in spike["evidence"])

    # --- performance -------------------------------------------------------
    status, prods = get("/api/analytics/product-performance")
    check("GET /api/analytics/product-performance works",
          status == 200 and prods["total"] == 36)
    chips = next(i for i in prods["items"] if i["product_id"] == 7)
    check("product performance reports units/avg/change",
          chips["units_sold"] > 0 and chips["average_daily_units"] > 0
          and chips["change_units_pct"] is not None and chips["trend"] in ("UP", "DOWN", "STABLE"))
    status, stores = get("/api/analytics/store-performance")
    check("GET /api/analytics/store-performance works", status == 200 and stores["total"] == 5)

    # --- filters -----------------------------------------------------------
    status, s1 = get("/api/analytics/stock-out-risks?store_id=1&limit=100")
    check("stock-out filtered by store", status == 200 and s1["total"] == 36
          and all(r["store_id"] == 1 for r in s1["items"]))
    status, p1 = get("/api/analytics/product-performance?product_id=1")
    check("product-performance filtered by product", status == 200 and p1["total"] == 1
          and p1["items"][0]["product_id"] == 1)
    status, sl = get("/api/analytics/slow-movers?product_id=34")
    check("slow-movers filtered by product", status == 200 and sl["total"] == 5
          and all(r["product_id"] == 34 for r in sl["items"]))
    status, a1 = get("/api/analytics/sales-anomalies?store_id=2&product_id=16")
    check("anomalies filtered by store+product", status == 200 and a1["total"] == 1)

    # --- custom dates ------------------------------------------------------
    status, perf = get("/api/analytics/product-performance?start_date=2026-01-01&end_date=2026-01-31")
    check("performance with explicit dates",
          status == 200 and perf["period_start"] == "2026-01-01" and perf["period_end"] == "2026-01-31")
    status, custom = get("/api/analytics/stock-out-risks?as_of_date=2026-01-15")
    check("stock-out with as_of_date", status == 200
          and custom["analysis_date"] == "2026-01-15"
          and custom["period_end"] == "2026-01-15")

    # --- demand forecast (Milestone 7) --------------------------------------
    status, forecast = get("/api/analytics/forecast?limit=50")
    check("GET /api/analytics/forecast works", status == 200 and forecast["total"] == 180)
    check("forecast defaults to a 7-day horizon", forecast["horizon_days"] == 7)
    check("forecast reports the analysis date",
          forecast["analysis_date"] == "2026-01-31")
    check("forecast marks all rows SUFFICIENT_DATA",
          forecast["forecast_status"] == "SUFFICIENT_DATA"
          and forecast["counts"]["by_forecast_status"]["SUFFICIENT_DATA"] == 180)
    check("forecast items expose demand/trend/outlook",
          all("recent_daily_demand" in row and "forecast_units" in row
              and "trend" in row and "inventory_outlook" in row for row in forecast["items"]))
    check("forecast items carry the requested horizon",
          all(row["horizon_days"] == 7 for row in forecast["items"]))
    check("forecast produces expected units for some rows",
          any(row["forecast_units"] > 0 for row in forecast["items"]))

    status, fer = get("/api/analytics/forecast-summary")
    check("GET /api/analytics/forecast-summary works",
          status == 200 and fer["horizon_days"] == 7)
    check("forecast summary expected figures are sane",
          fer["expected_daily_demand"] > 0
          and fer["expected_horizon_units"] >= fer["expected_daily_demand"])

    status, f30 = get("/api/analytics/forecast?horizon_days=30&limit=10")
    check("forecast accepts a 30-day horizon",
          status == 200 and f30["horizon_days"] == 30 and f30["total"] == 180)
    status, f14 = get("/api/analytics/forecast?horizon_days=14&limit=10")
    check("forecast accepts a 14-day horizon",
          status == 200 and f14["horizon_days"] == 14 and f14["total"] == 180)
    status, fprod = get("/api/analytics/forecast?product_id=7&limit=5")
    check("forecast filtered by product", status == 200 and fprod["total"] == 5
          and all(row["product_id"] == 7 for row in fprod["items"]))
    status, fstore = get("/api/analytics/forecast?store_id=1&limit=5")
    check("forecast filtered by store", status == 200 and fstore["total"] == 36
          and all(row["store_id"] == 1 for row in fstore["items"]))

    status, early = get("/api/analytics/forecast?as_of_date=2025-11-04&limit=50")
    check("early as_of_date forecast is INSUFFICIENT_DATA",
          status == 200 and early["forecast_status"] == "INSUFFICIENT_DATA")

    _, fd1 = get("/api/analytics/forecast?limit=50")
    _, fd2 = get("/api/analytics/forecast?limit=50")
    check("forecast responses are deterministic", fd1 == fd2)

    # --- determinism over HTTP ---------------------------------------------
    _, d1 = get("/api/analytics/stock-out-risks?limit=100")
    _, d2 = get("/api/analytics/stock-out-risks?limit=100")
    check("HTTP responses are deterministic", d1 == d2)

    # --- error handling ----------------------------------------------------
    expect_status("/api/analytics/stock-out-risks?store_id=999", 404)
    expect_status("/api/analytics/stock-out-risks?product_id=999", 404)
    expect_status("/api/analytics/product-performance?product_id=999", 404)
    expect_status("/api/analytics/store-performance?store_id=999", 404)
    expect_status("/api/analytics/stock-out-risks?as_of_date=2026-05-01", 400)
    expect_status("/api/analytics/product-performance?start_date=2026-02-01&end_date=2026-01-01", 400)
    expect_status("/api/analytics/sales-anomalies?start_date=not-a-date", 422)
    expect_status("/api/analytics/slow-movers?limit=-1", 400)
    expect_status("/api/analytics/slow-movers?limit=5000", 400)
    expect_status("/api/analytics/stock-out-risks?offset=-1", 400)
    expect_status("/api/analytics/forecast?horizon_days=5", 400)
    expect_status("/api/analytics/forecast?horizon_days=abc", 422)
    expect_status("/api/analytics/forecast-summary?horizon_days=99", 400)

    # --- regression: Milestone 2 endpoints still work ----------------------
    status, summary = get("/api/data/summary")
    check("regression: /api/data/summary still works",
          status == 200 and summary["counts"]["sales"] == 14450)
    expect_status("/api/sales?store_id=999", 404)

    # --- frontend exposes analytics status ---------------------------------
    def get_body(path: str):
        with urllib.request.urlopen(BASE_URL + path, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8")

    status, html = get_body("/")
    check("frontend includes analytics-status section", status == 200
          and 'id="analytics-stockout"' in html and 'id="analytics-range"' in html)
    check("frontend includes demand outlook section", status == 200
          and 'id="outlook-chart"' in html and 'id="outlook-tbody"' in html
          and 'id="outlook-rising"' in html)

    server.should_exit = True
    thread.join(timeout=10)

    if FAILURES:
        print("\nFailures:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nAll analytics API checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())