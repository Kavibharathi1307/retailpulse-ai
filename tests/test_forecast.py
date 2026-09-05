"""Unit tests for the deterministic demand forecast (Milestone 7).

Builds a small synthetic SQLite database with controlled demand patterns
(flat, rising, newcomer, declining, zero-demand, and near-threshold drift) and
verifies the exact forecast numbers, data-sufficiency states, trend labels,
inventory outlooks, and the "never fabricate when history is thin" contract.

Run from the project root:

    .venv\\Scripts\\python.exe -m unittest tests.test_forecast -v
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
from src.schema import apply_schema

START = date(2025, 11, 3)
N_DAYS = 90


def day(offset: int) -> date:
    return START + timedelta(days=offset)


def iso(offset: int) -> str:
    return day(offset).isoformat()


def _build_database(tmp: Path) -> Path:
    db = tmp / "forecast.db"
    conn = sqlite3.connect(db)
    apply_schema(conn)
    conn.execute(
        "INSERT INTO stores (store_id, store_name, city, region, active)"
        " VALUES (1, 'Test Store', 'Testville', 'Testland', 1)"
    )
    products = [
        (1, "Flat", "Test", 10.0),
        (2, "Riser", "Test", 11.0),
        (3, "Newcomer", "Test", 12.0),
        (4, "Decliner", "Test", 13.0),
        (5, "Zero", "Test", 14.0),
        (6, "Watch", "Test", 15.0),
        (7, "Buffer", "Test", 16.0),
        (8, "Drifty", "Test", 17.0),
    ]
    conn.executemany(
        "INSERT INTO products (product_id, product_name, category, unit_price, active)"
        " VALUES (?, ?, ?, ?, 1)",
        products,
    )

    def add(offset: int, pid: int, qty: int) -> None:
        conn.execute(
            "INSERT INTO sales (sale_date, store_id, product_id, quantity_sold, revenue)"
            " VALUES (?, 1, ?, ?, ?)",
            (iso(offset), pid, qty, round(qty * dict((p[0], p[3]) for p in products)[pid], 2)),
        )

    for i in range(N_DAYS):
        add(i, 1, 10)                # Flat: 10/day
        if i >= 70:
            add(i, 2, 20)            # Riser: only the last 20 days
        if i >= 83:
            add(i, 3, 15)            # Newcomer: only the recent window
        if i <= 60:
            add(i, 4, 30)            # Decliner: 30/day then 3/day
        else:
            add(i, 4, 3)
        # product 5: never sells
        add(i, 6, 10)                # Watch: 10/day
        add(i, 7, 10)                # Buffer: 10/day
        if i <= 72:
            add(i, 8, 10)            # Drifty: 10/day then 11/day
        else:
            add(i, 8, 11)

    inventory = [
        (1, 200, 50),
        (2, 100, 30),
        (3, 40, 20),
        (4, 500, 60),
        (5, 50, 10),
        (6, 75, 40),
        (7, 100, 50),
        (8, 132, 40),
    ]
    conn.executemany(
        "INSERT INTO inventory (store_id, product_id, current_stock, reorder_level, last_restock_date)"
        " VALUES (1, ?, ?, ?, '2026-01-31')",
        inventory,
    )
    conn.commit()
    conn.close()
    return db


class ForecastEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.db = _build_database(Path(cls._tmp.name))
        cls.as_of = day(N_DAYS - 1)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def item(self, horizon: int, product_id: int) -> dict:
        rows = A.forecast(self.db, as_of_date=self.as_of, horizon_days=horizon)["items"]
        return next(r for r in rows if r["product_id"] == product_id)

    # A. exact forecast numbers --------------------------------------------

    def test_flat_demand_forecast_stable_sufficient(self):
        row = self.item(7, 1)
        self.assertEqual(row["forecast_status"], "SUFFICIENT_DATA")
        self.assertEqual(row["recent_daily_demand"], 10.0)
        self.assertEqual(row["baseline_daily_demand"], 10.0)
        self.assertEqual(row["forecast_units"], 70.0)
        self.assertEqual(row["trend"], "STABLE")
        self.assertEqual(row["current_stock"], 200)
        self.assertEqual(row["expected_cover_days"], 20.0)
        self.assertEqual(row["inventory_outlook"], "SUFFICIENT")

    def test_horizon_14_extends_daily_rate(self):
        row = self.item(14, 1)
        self.assertEqual(row["horizon_days"], 14)
        self.assertEqual(row["forecast_units"], 140.0)

    def test_horizon_30_flips_inventory_to_at_risk(self):
        row = self.item(30, 1)
        self.assertEqual(row["forecast_units"], 300.0)
        self.assertEqual(row["inventory_outlook"], "AT_RISK")

    def test_rising_trend_and_forecast(self):
        row = self.item(7, 2)
        self.assertEqual(row["trend"], "UP")
        self.assertEqual(row["recent_daily_demand"], 20.0)
        self.assertEqual(row["baseline_daily_demand"], 9.29)
        self.assertEqual(row["forecast_units"], 140.0)

    def test_newcomer_with_empty_baseline_is_up(self):
        row = self.item(7, 3)
        self.assertEqual(row["trend"], "UP")
        self.assertEqual(row["baseline_daily_demand"], 0.0)
        self.assertEqual(row["forecast_units"], 105.0)
        self.assertEqual(row["inventory_outlook"], "AT_RISK")
        self.assertEqual(row["expected_cover_days"], 2.7)

    def test_declining_trend_and_forecast(self):
        row = self.item(14, 4)
        self.assertEqual(row["trend"], "DOWN")
        self.assertEqual(row["recent_daily_demand"], 3.0)
        self.assertEqual(row["baseline_daily_demand"], 8.79)
        self.assertEqual(row["forecast_units"], 42.0)
        self.assertEqual(row["inventory_outlook"], "SUFFICIENT")

    def test_zero_demand_forecasts_zero(self):
        row = self.item(7, 5)
        self.assertEqual(row["forecast_status"], "SUFFICIENT_DATA")
        self.assertEqual(row["recent_daily_demand"], 0.0)
        self.assertEqual(row["forecast_units"], 0.0)
        self.assertEqual(row["trend"], "STABLE")
        self.assertIsNone(row["expected_cover_days"])
        self.assertEqual(row["inventory_outlook"], "SUFFICIENT")

    def test_inventory_watch_band(self):
        row = self.item(7, 6)
        self.assertEqual(row["forecast_units"], 70.0)
        self.assertEqual(row["inventory_outlook"], "WATCH")

    def test_inventory_sufficient_buffer(self):
        row = self.item(7, 7)
        self.assertEqual(row["forecast_units"], 70.0)
        self.assertEqual(row["inventory_outlook"], "SUFFICIENT")

    def test_drift_below_threshold_stays_stable(self):
        row = self.item(30, 8)
        self.assertEqual(row["trend"], "STABLE")
        self.assertEqual(row["recent_daily_demand"], 11.0)
        self.assertEqual(row["baseline_daily_demand"], 10.36)

    # B. data sufficiency ---------------------------------------------------

    def test_insufficient_history_never_fabricates(self):
        rows = A.forecast(self.db, as_of_date=day(2), product_id=1)["items"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["forecast_status"], "INSUFFICIENT_DATA")
        self.assertEqual(row["recent_daily_demand"], None)
        self.assertEqual(row["baseline_daily_demand"], None)
        self.assertEqual(row["forecast_units"], None)
        self.assertEqual(row["trend"], "UNKNOWN")
        self.assertEqual(row["expected_cover_days"], None)
        self.assertEqual(row["inventory_outlook"], "INSUFFICIENT_DATA")
        self.assertEqual(row["evidence"]["recent_window_days"], 3)
        self.assertIn("Insufficient", row["explanation"])

    def test_limited_data_partial_baseline(self):
        rows = A.forecast(self.db, as_of_date=day(10), product_id=1)["items"]
        row = rows[0]
        self.assertEqual(row["forecast_status"], "LIMITED_DATA")
        self.assertEqual(row["evidence"]["recent_window_days"], 7)
        self.assertEqual(row["evidence"]["baseline_window_days"], 4)
        self.assertEqual(row["recent_daily_demand"], 10.0)
        self.assertEqual(row["forecast_units"], 70.0)
        self.assertEqual(row["trend"], "STABLE")

    def test_insufficient_rows_excluded_from_demand_outlook(self):
        insufficient = A.forecast(self.db, as_of_date=day(2))["items"]
        self.assertTrue(all(r["forecast_status"] == "INSUFFICIENT_DATA" for r in insufficient))
        summary = A.forecast_summary(self.db, as_of_date=day(2))
        self.assertEqual(summary["forecastable_total"], 0)
        self.assertEqual(summary["expected_daily_demand"], 0.0)
        self.assertEqual(summary["expected_horizon_units"], 0.0)

    # C. aggregation --------------------------------------------------------

    def test_summary_counts(self):
        summary = A.forecast_summary(self.db, as_of_date=self.as_of, horizon_days=7)
        self.assertEqual(summary["analysis_date"], iso(N_DAYS - 1))
        self.assertEqual(summary["horizon_days"], 7)
        self.assertEqual(summary["forecast_status"], "SUFFICIENT_DATA")
        self.assertEqual(summary["counts"]["total"], 8)
        self.assertEqual(summary["counts"]["by_trend"]["UP"], 2)
        self.assertEqual(summary["counts"]["by_trend"]["DOWN"], 1)
        self.assertEqual(summary["counts"]["by_forecast_status"]["SUFFICIENT_DATA"], 8)
        self.assertEqual(summary["forecastable_total"], 8)
        self.assertEqual(summary["expected_daily_demand"], 79.0)
        self.assertEqual(summary["expected_horizon_units"], 553.0)

    def test_determinism(self):
        first = A.forecast(self.db, as_of_date=self.as_of, horizon_days=7)
        second = A.forecast(self.db, as_of_date=self.as_of, horizon_days=7)
        self.assertEqual(first, second)

    # D. filters and contract ----------------------------------------------

    def test_product_filter(self):
        rows = A.forecast(self.db, product_id=1)["items"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_id"], 1)

    def test_non_positive_horizon_rejected(self):
        with self.assertRaises(ValueError):
            A.forecast(self.db, as_of_date=self.as_of, horizon_days=0)

    def test_missing_store_returns_empty(self):
        rows = A.forecast(self.db, store_id=999)["items"]
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)