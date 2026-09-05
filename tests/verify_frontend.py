"""HTTP-level verification of the Milestone 5 dashboard + UX.

Starts the real application in a background thread (as ``python app.py``
would), swaps in a fake Gemini client so the copilot never touches the
network, and checks the two-stage pipeline meets the M1-M5 contracts:

* served frontend contains every required element (brand, track badge,
  hero copilot, KPIs, health bar, store panel, chart, attention centre,
  product table, dataset strip, status pills)
* every dashboard number is served by a real endpoint (no fakery), and
  the KPI sources agree with the underlying dataset
* served JS treats Gemini output as untrusted text and never exposes the
  API key or unsafe sinks

Run from the project root:

    .venv\\Scripts\\python.exe tests/verify_frontend.py
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

from src.copilot_api import copilot_service

from app import app

BASE_URL = "http://127.0.0.1:8000"
FAILURES = []


class FakeClient:
    """Deterministic stand-in for GeminiClient (no network in tests)."""

    is_configured = True
    model = "fake-model"

    def __init__(self, response: str = "Three stores need priority replenishment."):
        self.response = response
        self.calls = 0

    def generate(self, system_instruction: str, user_prompt: str) -> str:
        self.calls += 1
        return self.response


def request(path: str, method: str = "GET", body: str | None = None):
    headers = {}
    data = None
    if body is not None:
        data = body.encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, raw


def get_json(path: str):
    status, raw = request(path)
    return status, json.loads(raw)


def post_json(path: str, payload):
    return request(path, method="POST", body=json.dumps(payload))


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
            status, _ = get_json("/api/health")
            if status == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print("FAIL server did not become ready")
        return 1

    # ---- Shell & brand -----------------------------------------------------
    status, html = request("/")
    check("frontend serves at /", status == 200)
    check("brand wordmark present",
          "RetailPulse&nbsp;AI" in html and "AI-Powered Sales &amp; Inventory Copilot" in html)
    check("track badge PS03 present", "NexusTiQ24" in html and "PS03" in html)
    check("primary nav present", "Dashboard" in html and "Copilot" in html and "Analytics" in html)
    check("status pills present", 'id="status-backend"' in html and 'id="status-gemini"' in html)

    # ---- Copilot hero ------------------------------------------------------
    check("copilot hero present",
          'id="copilot-form"' in html and 'id="copilot-question"' in html and 'id="copilot-ask"' in html)
    check("seven suggestion chips shipped", html.count('class="suggestion-chip"') == 7)
    check("copilot answer/evidence/assumptions containers present",
          'id="copilot-answer"' in html and 'id="copilot-evidence"' in html
          and 'id="copilot-assumptions"' in html and 'id="copilot-result"' in html)
    check("all six JS modules loaded",
          all(href in html for href in (
              "/assets/utils.js", "/assets/api.js", "/assets/charts.js",
              "/assets/copilot.js", "/assets/dashboard.js", "/assets/app.js",
          )))

    # ---- Dashboard sections ------------------------------------------------
    for element_id in (
        "kpi-latest-sales", "kpi-revenue", "kpi-stock", "kpi-risk", "kpi-attention",
        "analytics-stockout", "health-overstock", "health-slow", "health-flagged", "health-ok",
        "store-list", "sales-chart", "attention-list", "attention-count",
        "product-table", "product-tbody", "product-category-filter",
        "data-stores", "data-products", "data-sales", "data-inventory", "global-analysis-date",
        "outlook-chart", "outlook-tbody", "outlook-rising", "outlook-falling",
        "outlook-at-risk", "outlook-watch", "outlook-thin", "outlook-note", "outlook-count",
        "executive", "exec-health-score", "exec-health-status", "exec-health-explanation",
        "exec-health-formula", "exec-health-components", "exec-revenue", "exec-units",
        "exec-critical", "exec-recommendations", "exec-forecast-at-risk",
        "exec-top-issues", "exec-growth", "exec-decline",
        "exec-top-count", "exec-growth-count", "exec-decline-count", "executive-note",
    ):
        check(f"dashboard element id={element_id}", f'id="{element_id}"' in html)
    check("executive section labelled in the page",
          "Executive Overview" in html and "How is this score calculated?" in html)

    # ---- Truthful numbers: every value must come from a real endpoint ------
    status, summary = get_json("/api/data/summary")
    check("data summary served",
          status == 200 and summary["counts"] == {"stores": 5, "products": 36, "inventory": 180, "sales": 14450})

    status, series = get_json("/api/data/sales-series")
    items = series.get("items") or []
    check("sales-series served with daily points", status == 200 and len(items) > 0)
    check("sales-series rows well-formed",
          all("sale_date" in row and "units" in row and "revenue" in row for row in items))
    check("sales-series has real revenue", sum(row["revenue"] for row in items) > 0)
    check("sales-series covers the analysis window",
          items[0]["sale_date"] <= summary["last_date"] and items[-1]["sale_date"] == summary["last_date"])

    status, attention = get_json("/api/analytics/attention-summary?limit=1000")
    check("attention-summary served", status == 200 and attention["counts"]["total"] > 0)
    cat_key_sum = attention["counts"].get("stock_out_risks", 0) + attention["counts"].get("overstock", 0) \
        + attention["counts"].get("slow_movers", 0) + attention["counts"].get("sales_spikes", 0) \
        + attention["counts"].get("sales_drops", 0)
    check("attention counts internally consistent", attention["counts"]["total"] == cat_key_sum)
    check("attention rows all carry issue metadata",
          all("issue_type" in row and "severity" in row and "explanation" in row for row in attention["items"]))

    status, stockouts = get_json("/api/analytics/stock-out-risks?limit=1000")
    critical_high = sum(1 for row in stockouts["items"] if row["status"] in ("CRITICAL", "HIGH"))
    check("KPI risk source: CRITICAL+HIGH == 50", critical_high == 50)
    check("stock-out rows carry store/product ids",
          all("store_id" in row and "product_id" in row and "days_of_stock" in row for row in stockouts["items"]))

    status, overstock = get_json("/api/analytics/overstock?limit=1000")
    check("overstock count == 19",
          status == 200 and sum(1 for row in overstock["items"] if row["status"] == "OVERSTOCK") == 19)

    status, slow = get_json("/api/analytics/slow-movers?limit=1000")
    check("slow movers count == 15",
          status == 200 and sum(1 for row in slow["items"] if row["status"] == "SLOW_MOVER") == 15)

    status, stores = get_json("/api/analytics/store-performance?limit=1000")
    check("store performance covers 5 stores", status == 200 and stores["total"] == 5)
    check("store rows carry revenue/units/trend",
          all("revenue" in row and "units_sold" in row and "trend" in row for row in stores["items"]))

    status, products = get_json("/api/analytics/product-performance?limit=1000")
    check("product performance covers 36 products", status == 200 and products["total"] == 36)

    status, forecast_summary = get_json("/api/analytics/forecast-summary?horizon_days=14")
    check("forecast-summary served for 14 days",
          status == 200 and forecast_summary["horizon_days"] == 14
          and forecast_summary["forecast_status"] == "SUFFICIENT_DATA")
    check("forecast-summary has totals",
          forecast_summary["counts"]["total"] == 180
          and forecast_summary["expected_daily_demand"] > 0)
    status, forecast_items = get_json("/api/analytics/forecast?horizon_days=14&limit=1000")
    check("forecast served for 14 days", status == 200 and forecast_items["total"] == 180)
    check("forecast rows carry trend and outlook",
          all("recent_daily_demand" in row and "forecast_units" in row
              and "trend" in row and "inventory_outlook" in row for row in forecast_items["items"]))
    check("forecast-summary matches forecast row counts",
          forecast_items["counts"]["total"] == forecast_summary["counts"]["total"])

    status, health = get_json("/api/health")
    check("health endpoint intact", status == 200 and health["track"] == "PS03")

    # ---- Executive Overview (Milestone 8): numbers come from the engine ----
    status, executive = get_json("/api/analytics/executive-summary")
    check("executive-summary served",
          status == 200 and isinstance(executive["health"]["score"], int)
          and executive["health"]["status"] in ("EXCELLENT", "HEALTHY", "WATCH", "AT_RISK", "CRITICAL"))
    check("executive analysis date is the dataset analysis date",
          executive["analysis_date"] == summary["last_date"])
    check("executive top lists have engine-grounded rows",
          all("product" in row and "store" in row
              and ("short_reason" in row or "reason" in row) for row in executive["top_issues"])
          and len(executive["top_opportunities"]) > 0
          and len(executive["top_declines"]) > 0)

    status, dash_js = request("/assets/dashboard.js")
    check("dashboard.js renders the executive summary",
          "renderExecutive" in dash_js
          and "/api/analytics/executive-summary" in dash_js
          and "exec-health-score" in dash_js)
    check("executive data rendered via textContent",
          "statusEl.textContent = health.status" in dash_js
          and "container.textContent = \"\"" in dash_js)

    # ---- Copilot path (Gemini swapped for a fake, no network) --------------
    fake = FakeClient()
    copilot_service.client = fake
    status, raw = post_json("/api/copilot/query", {"question": "Which products are at risk of stock-out?"})
    body = json.loads(raw)
    check("copilot query returns 200", status == 200)
    check("copilot answer grounded in engine evidence",
          body["grounded"] is True and len(body["evidence"]) > 0 and body["answer"])
    check("copilot response never leaks the key name",
          "GEMINI_API_KEY" not in raw and "api_key" not in raw and "apiKey" not in raw)

    status, raw = post_json("/api/copilot/query", {"question": "What demand should I expect next week?"})
    body = json.loads(raw)
    check("copilot answers a demand-forecast question",
          status == 200 and body["grounded"] is True
          and any(ev.get("type") == "FORECAST_SUMMARY" for ev in body["evidence"])
          and any(ev.get("type") == "FORECAST" for ev in body["evidence"]))

    # ---- Served assets: untrusted-text rendering + no secrets --------------
    for asset in ("utils.js", "api.js", "charts.js", "copilot.js", "dashboard.js", "app.js", "styles.css"):
        status, content = request(f"/assets/{asset}")
        check(f"asset /assets/{asset} served", status == 200)
        check(f"asset {asset} has no key", "GEMINI_API_KEY" not in content)

    status, copilot_js = request("/assets/copilot.js")
    check("Gemini output rendered via textContent",
          "answer.textContent = data.answer" in copilot_js and "addListItem" in copilot_js)
    check("no innerHTML sink for dynamic answer", "answer.innerHTML = data.answer" not in copilot_js)

    served_js = ""
    for asset in ("utils.js", "api.js", "charts.js", "copilot.js", "dashboard.js", "app.js"):
        _, content = request(f"/assets/{asset}")
        served_js += content
    check("no unsafe sinks across served JS",
          "insertAdjacentHTML" not in served_js and "innerHTML = data.answer" not in served_js)

    server.should_exit = True
    thread.join(timeout=10)

    if FAILURES:
        print("\nFailures:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nAll frontend checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())