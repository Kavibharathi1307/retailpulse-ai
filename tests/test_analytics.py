"""Unit tests for the deterministic retail analytics engine (Milestone 3).

Builds a small synthetic SQLite database with controlled patterns (daily
seller, zero-sales product, slow mover, overstocked product, spike, drop,
short-history product) and verifies the exact numbers and statuses produced by
the analytics modules.

Run from the project root:

    .venv\\Scripts\\python.exe -m unittest tests.test_analytics -v
"""

import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics import engine as A
from src.analytics.config import DEFAULT_CONFIG as CONFIG
from src.analytics.metrics import demand_stats
from src.schema import apply_schema

START = date(2025, 11, 3)
N_DAYS = 90


def day(offset: int) -> date:
    return START + timedelta(days=offset)


def iso(offset: int) -> str:
    return day(offset).isoformat()


def _build_database(tmp: Path) -> Path:
    db = tmp / "retail.db"
    conn = sqlite3.connect(db)
    apply_schema(conn)
    conn.execute(
        "INSERT INTO stores (store_id, store_name, city, region, active) VALUES (1, 'Test Store', 'Testville', 'Testland', 1)"
    )
    products = [
        (1, "Fast Mover", "Test", 10.0),
        (2, "Zero Seller", "Test", 5.0),
        (3, "Slow Mover", "Test", 2.0),
        (4, "Overstocked", "Test", 8.0),
        (5, "Spiker", "Test", 4.0),
        (6, "Dropper", "Test", 6.0),
        (7, "Short History", "Test", 3.0),
    ]
    conn.executemany(
        "INSERT INTO products (product_id, product_name, category, unit_price, active) VALUES (?, ?, ?, ?, 1)",
        products,
    )

    def add_sale(offset: int, pid: int, qty: int) -> None:
        conn.execute(
            "INSERT INTO sales (sale_date, store_id, product_id, quantity_sold, revenue)"
            " VALUES (?, 1, ?, ?, ?)",
            (iso(offset), pid, qty, round(qty * dict((p[0], p[3]) for p in products)[pid], 2)),
        )

    for i in range(N_DAYS):
        add_sale(i, 1, 10)          # Fast Mover: 10/day flat
        add_sale(i, 4, 10)          # Overstocked: 10/day flat
        if i % 5 == 0:
            add_sale(i, 3, 1)       # Slow Mover: 1 unit every 5 days
        if i <= 62:
            add_sale(i, 5, 5)       # Spiker baseline: 5/day
        else:
            add_sale(i, 5, 25)      # Spiker surge: 25/day
        if i <= 75:
            add_sale(i, 6, 30)      # Dropper baseline: 30/day
        else:
            add_sale(i, 6, 2)       # Dropper collapse: 2/day
        if i >= 85:
            add_sale(i, 7, 5)       # Short History: only last 5 days
        # product 2: no sales at all

    inventory = [
        (1, 25, 100),    # Fast Mover -> 2.5 days -> CRITICAL
        (2, 50, 10),     # Zero Seller -> UNKNOWN
        (3, 100, 20),    # Slow Mover -> 100 / ~0.18 = OVERSTOCK + SLOW_MOVER
        (4, 700, 100),   # Overstocked -> 70 days cover -> OVERSTOCK
        (5, 100, 30),
        (6, 80, 40),
        (7, 100, 5),
    ]
    conn.executemany(
        "INSERT INTO inventory (store_id, product_id, current_stock, reorder_level, last_restock_date)"
        " VALUES (1, ?, ?, ?, '2026-01-31')",
        inventory,
    )
    conn.commit()
    conn.close()
    return db


class AnalyticsEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.db = _build_database(Path(cls._tmp.name))
        cls.as_of = day(N_DAYS - 1)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # A. normal performance ------------------------------------------------

    def test_fast_mover_performance_normal(self):
        result = A.product_performance(self.db, as_of_date=self.as_of)
        item = next(i for i in result["items"] if i["product_id"] == 1)
        self.assertEqual(item["units_sold"], 280)
        self.assertEqual(item["average_daily_units"], 10.0)
        self.assertEqual(item["previous_units_sold"], 280)
        self.assertEqual(item["change_units_pct"], 0.0)
        self.assertEqual(item["trend"], "STABLE")
        self.assertEqual(item["period_days"], 28)

    def test_performance_reports_analysis_date(self):
        result = A.product_performance(self.db, as_of_date=self.as_of)
        self.assertEqual(result["analysis_date"], iso(N_DAYS - 1))
        item = result["items"][0]
        self.assertIn("analysis_date", item)
        self.assertIn("period_start", item)
        self.assertIn("period_end", item)

    # B. zero-sales product ------------------------------------------------

    def test_zero_sales_product_stock_unknown_no_fabricated_date(self):
        rows = A.stockout_risks(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 2)
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertEqual(row["data_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(row["days_of_stock"])
        self.assertIsNone(row["estimated_stock_out_date"])

    def test_zero_sales_product_not_slow_mover(self):
        rows = A.slow_movers(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 2)
        self.assertEqual(row["status"], "INSUFFICIENT_DATA")

    def test_zero_sales_product_performance_is_zero(self):
        result = A.product_performance(self.db, as_of_date=self.as_of)
        item = next(i for i in result["items"] if i["product_id"] == 2)
        self.assertEqual(item["units_sold"], 0)
        self.assertEqual(item["average_daily_units"], 0.0)
        self.assertIsNone(item["change_units_pct"])

    # C. stock-out calculation ----------------------------------------------

    def test_stock_out_calculation(self):
        rows = A.stockout_risks(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 1)
        self.assertEqual(row["current_stock"], 25)
        self.assertEqual(row["average_daily_sales"], 10.0)
        self.assertEqual(row["days_of_stock"], 2.5)
        self.assertEqual(row["status"], "CRITICAL")
        self.assertTrue(row["below_reorder"])
        self.assertEqual(row["estimated_stock_out_date"], day(N_DAYS - 1 + 3).isoformat())

    def test_stock_out_no_estimate_for_zero_sales(self):
        rows = A.stockout_risks(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 2)
        self.assertIsNone(row["estimated_stock_out_date"])
        self.assertIn("cannot be estimated", row["explanation"])

    # D. overstock ----------------------------------------------------------

    def test_overstock_detection(self):
        rows = A.overstock(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 4)
        self.assertEqual(row["stock_cover_days"], 70.0)
        self.assertEqual(row["status"], "OVERSTOCK")

    # E. slow movers --------------------------------------------------------

    def test_slow_mover_detection(self):
        rows = A.slow_movers(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 3)
        self.assertEqual(row["status"], "SLOW_MOVER")
        self.assertLessEqual(row["average_daily_sales"], CONFIG.slow_mover_daily_units)
        self.assertGreaterEqual(row["sales_days"], CONFIG.slow_mover_min_sales_days)

    # F. sales anomalies ----------------------------------------------------

    def test_spike_detection(self):
        rows = A.sales_anomalies(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 5)
        self.assertEqual(row["direction"], "SPIKE")
        self.assertGreaterEqual(row["change_pct"], CONFIG.spike_threshold_pct)
        self.assertGreaterEqual(row["recent_units"], CONFIG.min_anomaly_change_units)
        self.assertIn("evidence", row)
        self.assertIn("recent_window_start", row["evidence"])

    def test_drop_detection(self):
        rows = A.sales_anomalies(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 6)
        self.assertEqual(row["direction"], "DROP")
        self.assertLessEqual(row["change_pct"], -CONFIG.drop_threshold_pct)

    def test_flat_series_is_normal(self):
        rows = A.sales_anomalies(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 1)
        self.assertEqual(row["direction"], "NORMAL")

    def test_short_history_anomaly_insufficient(self):
        rows = A.sales_anomalies(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 7)
        self.assertEqual(row["direction"], "INSUFFICIENT_DATA")

    # G. insufficient data --------------------------------------------------

    def test_demand_stats_short_window_insufficient(self):
        series = {day(i): {"units": 10, "revenue": 10.0} for i in range(3)}
        stats = demand_stats(series, day(0), day(2), min_history_days=CONFIG.min_history_days)
        self.assertEqual(stats["data_status"], "INSUFFICIENT_DATA")

    def test_insufficient_history_not_flagged_as_spike(self):
        rows = A.sales_anomalies(self.db, as_of_date=self.as_of)["items"]
        row = next(r for r in rows if r["product_id"] == 7)
        self.assertEqual(row["direction"], "INSUFFICIENT_DATA")

    # H. attention summary --------------------------------------------------

    def test_attention_summary_structure(self):
        summary = A.attention_summary(self.db, as_of_date=self.as_of)
        self.assertIn("counts", summary)
        self.assertIn("items", summary)
        self.assertEqual(summary["counts"]["total"], len(summary["items"]))
        by_product = {item["product_id"]: item for item in summary["items"]}
        self.assertEqual(by_product[1]["severity"], "CRITICAL")
        self.assertEqual(by_product[1]["issue_type"], "STOCK_OUT_RISK")
        self.assertTrue(any(item["issue_type"] == "SLOW_MOVER" for item in summary["items"]))
        self.assertTrue(any(item["issue_type"] == "SALES_SPIKE" for item in summary["items"]))
        self.assertTrue(any(item["issue_type"] == "SALES_DROP" for item in summary["items"]))

    def test_determinism(self):
        first = A.attention_summary(self.db, as_of_date=self.as_of)
        second = A.attention_summary(self.db, as_of_date=self.as_of)
        self.assertEqual(first, second)

    # I. invalid parameters -------------------------------------------------

    def test_start_after_end_rejected(self):
        with self.assertRaises(ValueError):
            A.product_performance(
                self.db, as_of_date=self.as_of, start_date=day(20), end_date=day(10)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)