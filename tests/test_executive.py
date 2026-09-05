"""Milestone 8 -- deterministic executive intelligence tests.

Verifies the executive summary contract: the explainable Retail Health score,
the ranked top issues/opportunities/declines, the business and inventory
snapshots, store/date filters, limit handling, determinism, and the hard rule
that NO financial metrics (profit, margin, savings, ROI) are ever fabricated.

Run from the project root:

    .venv\\Scripts\\python.exe -m unittest tests.test_executive -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from app import app
from src.analytics import data
from src.analytics import engine
from src.analytics.config import DEFAULT_CONFIG
from src.analytics.executive import status_for_score


def _walk_keys(obj, keys):
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.add(str(key).lower())
            _walk_keys(value, keys)
    elif isinstance(obj, list):
        for item in obj:
            _walk_keys(item, keys)


class ExecutiveEngineTest(unittest.TestCase):
    def setUp(self):
        self.summary = engine.executive()

    def test_health_score_and_status_match_portfolio(self):
        self.assertEqual(self.summary["health"]["score"], 66)
        self.assertEqual(self.summary["health"]["status"], "WATCH")
        self.assertEqual(self.summary["analysis_date"], "2026-01-31")

    def test_health_score_recomputes_from_components(self):
        health = self.summary["health"]
        self.assertEqual(health["penalty_total"], round(sum(c["penalty"] for c in health["components"]), 2))
        self.assertEqual(health["score"], max(0, round(100 - health["penalty_total"])))

    def test_health_has_five_transparent_components(self):
        health = self.summary["health"]
        keys = [c["key"] for c in health["components"]]
        self.assertEqual(
            keys, ["stock_out", "forecast_risk", "overstock", "slow_movers", "anomalies"]
        )
        for component in health["components"]:
            self.assertGreaterEqual(component["penalty"], 0)
            self.assertEqual(component["denominator"], health["denominator"])

    def test_status_bands_are_inclusive_lower_bound(self):
        config = DEFAULT_CONFIG
        self.assertEqual(status_for_score(config.health_status_excellent, config), "EXCELLENT")
        self.assertEqual(status_for_score(config.health_status_excellent - 1, config), "HEALTHY")
        self.assertEqual(status_for_score(config.health_status_healthy, config), "HEALTHY")
        self.assertEqual(status_for_score(config.health_status_watch, config), "WATCH")
        self.assertEqual(status_for_score(config.health_status_at_risk, config), "AT_RISK")
        self.assertEqual(status_for_score(config.health_status_at_risk - 1, config), "CRITICAL")

    def test_counts_match_engine_reality(self):
        counts = self.summary["counts"]
        self.assertEqual(counts["total_stores"], 5)
        self.assertEqual(counts["total_products"], 36)
        self.assertEqual(counts["critical_issue_count"], 15)
        self.assertEqual(counts["high_issue_count"], 35)
        self.assertEqual(counts["stockout_risk_count"], 50)
        self.assertEqual(counts["overstock_count"], 19)
        self.assertEqual(counts["slow_mover_count"], 15)
        self.assertEqual(counts["anomaly_count"], 22)
        self.assertEqual(counts["recommendation_count"], 106)
        self.assertEqual(counts["forecast_at_risk_count"], 15)
        self.assertEqual(counts["rising_product_count"], 36)
        self.assertEqual(counts["declining_product_count"], 40)

    def test_top_issues_ranked_critical_first(self):
        issues = self.summary["top_issues"]
        self.assertEqual(len(issues), DEFAULT_CONFIG.executive_default_limit)
        self.assertEqual(issues[0]["priority"], "CRITICAL")
        self.assertEqual([i["rank"] for i in issues], list(range(1, len(issues) + 1)))

    def test_top_issues_carry_actionable_fields(self):
        issue = self.summary["top_issues"][0]
        for key in ("issue_type", "recommendation_type", "priority", "product", "store",
                    "short_reason", "reason", "recommended_action", "data_status"):
            self.assertIn(key, issue)
        self.assertEqual(issue["recommendation_type"], "REPLENISH")
        self.assertEqual(issue["data_status"], "SUFFICIENT")

    def test_top_opportunities_are_grounded_signals(self):
        opponents = self.summary["top_opportunities"]
        self.assertTrue(opponents)
        for opp in opponents:
            self.assertIn(opp["signal"], {"Rising demand", "Sales spike"})
            self.assertEqual(opp["category"], "Demand opportunity")
            self.assertIn(opp["metric"], {"recent_daily_demand", "change_pct"})
            self.assertEqual(opp["rank"], opponents.index(opp) + 1)
            self.assertGreaterEqual(opp.get("change_pct") or 0, 0)

    def test_top_declines_are_grounded_signals(self):
        declines = self.summary["top_declines"]
        self.assertTrue(declines)
        for dec in declines:
            self.assertIn(dec["signal"], {"Declining demand", "Sales drop", "Slow mover"})
            self.assertEqual(dec["rank"], declines.index(dec) + 1)
            self.assertIn(dec["metric"], {"recent_daily_demand", "change_pct", "average_daily_sales"})

    def test_top_lists_have_no_duplicate_positions(self):
        for field in ("top_issues", "top_opportunities", "top_declines"):
            entries = self.summary[field]
            keys = [(e.get("store_id"), e.get("product_id")) for e in entries]
            self.assertEqual(len(keys), len(set(keys)), field)

    def test_inventory_snapshot_matches_counts(self):
        inv = self.summary["inventory_snapshot"]
        counts = self.summary["counts"]
        self.assertEqual(inv["total_inventory_records"], 180)
        self.assertEqual(inv["critical_stockout"] + inv["high_stockout"], counts["stockout_risk_count"])
        self.assertEqual(inv["overstock"], counts["overstock_count"])
        self.assertEqual(inv["slow_movers"], counts["slow_mover_count"])
        self.assertEqual(inv["forecast_at_risk"], counts["forecast_at_risk_count"])

    def test_store_filter_rescales_denominators(self):
        summary = engine.executive(store_id=2)
        health = summary["health"]
        self.assertEqual(summary["counts"]["total_stores"], 1)
        self.assertEqual(health["denominator"], 36)
        self.assertEqual(summary["inventory_snapshot"]["total_inventory_records"], 36)
        for component in health["components"]:
            self.assertEqual(component["denominator"], 36)

    def test_no_fabricated_financial_metrics(self):
        forbidden = {"profit", "margin", "savings", "roi", "monetary", "cost"}
        keys = set()
        _walk_keys(self.summary, keys)
        self.assertTrue(forbidden.isdisjoint(keys))

    def test_determinism(self):
        first = engine.executive()
        second = engine.executive(store_id=1)
        again = engine.executive(store_id=1)
        self.assertEqual(second, again)
        self.assertNotEqual(first["counts"]["stockout_risk_count"], second["counts"]["stockout_risk_count"])


class ExecutiveApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_endpoint_returns_executive_summary(self):
        response = self.client.get("/api/analytics/executive-summary")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["health"]["score"], 66)
        self.assertEqual(body["analysis_date"], "2026-01-31")
        self.assertIn("top_issues", body)
        self.assertIn("top_opportunities", body)
        self.assertIn("top_declines", body)
        self.assertIn("inventory_snapshot", body)

    def test_limit_regulates_top_lists(self):
        self.assertEqual(
            len(self.client.get("/api/analytics/executive-summary?limit=2").json()["top_issues"]), 2
        )
        maxed = self.client.get(f"/api/analytics/executive-summary?limit={DEFAULT_CONFIG.executive_max_limit}")
        self.assertEqual(maxed.status_code, 200)
        self.assertLessEqual(len(maxed.json()["top_issues"]), DEFAULT_CONFIG.executive_max_limit)

    def test_invalid_limit_rejected(self):
        self.assertEqual(self.client.get("/api/analytics/executive-summary?limit=0").status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/analytics/executive-summary?limit={DEFAULT_CONFIG.executive_max_limit + 1}").status_code,
            400,
        )

    def test_unknown_store_rejected(self):
        self.assertEqual(
            self.client.get("/api/analytics/executive-summary?store_id=999").status_code, 404
        )

    def test_store_filter_changes_health(self):
        body = self.client.get("/api/analytics/executive-summary?store_id=2").json()
        self.assertEqual(body["counts"]["total_stores"], 1)
        self.assertEqual(body["health"]["denominator"], 36)

    def test_as_of_date_is_supported(self):
        as_of = date(2026, 1, 10)
        body = self.client.get(f"/api/analytics/executive-summary?as_of_date={as_of.isoformat()}").json()
        self.assertEqual(body["analysis_date"], as_of.isoformat())
        self.assertIsInstance(body["health"]["score"], int)

    def test_early_history_still_resilient(self):
        body = self.client.get("/api/analytics/executive-summary?as_of_date=2025-11-04").json()
        self.assertIsInstance(body["health"]["score"], int)
        self.assertIn("top_issues", body)
        self.assertIn("inventory_snapshot", body)


if __name__ == "__main__":
    unittest.main()