"""HTTP-level verification of the Milestone 4 copilot API + frontend.

Starts the real application in a background thread (as ``python app.py``
would), replaces the copilot service's Gemini client with a fake so the
test never touches the network, and exercises the copilot endpoint and the
new frontend over real HTTP.

Run from the project root:

    .venv\\Scripts\\python.exe tests/verify_copilot_api.py
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
from src.gemini.client import GeminiClient
from src.gemini.config import GeminiConfig
from src.gemini.errors import (
    GeminiAPIError,
    GeminiTimeoutError,
)

from app import app

BASE_URL = "http://127.0.0.1:8000"
FAILURES = []


class FakeClient:
    """Replaces the real Gemini client during the HTTP scenarios."""

    is_configured = True
    model = "fake-model"

    def __init__(self, response: str = "Grounded answer."):
        self.response = response
        self.calls = 0

    def generate(self, system_instruction: str, user_prompt: str) -> str:
        self.calls += 1
        return self.response


def request(
    path: str,
    method: str = "GET",
    body: str | None = None,
    content_type: str = "application/json",
):
    headers = {}
    data = None
    if body is not None:
        data = body.encode("utf-8")
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, raw


def post_json(path: str, payload):
    return request(path, method="POST", body=json.dumps(payload))


def get_json(path: str):
    status, raw = request(path)
    return status, json.loads(raw)


def expect_status(path: str, method: str, body: str | None, expected: int) -> None:
    try:
        status, _ = request(path, method=method, body=body)
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
            status, _ = get_json("/api/health")
            if status == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print("FAIL server did not become ready")
        return 1

    # ---- Frontend presence -------------------------------------------------
    status, html = request("/")
    check("frontend serves copilot UI", status == 200)
    check("frontend has copilot panel",
          'id="copilot-form"' in html and 'id="copilot-question"' in html and 'id="copilot-ask"' in html)
    check("frontend has suggestion chips",
          'class="suggestion-chip"' in html and 'id="copilot-suggestions"' in html)
    check("frontend has evidence/assumptions sections",
          'id="copilot-evidence"' in html and 'id="copilot-assumptions"' in html)

    # ---- Gemini-available path ---------------------------------------------
    fake = FakeClient("Chips in store 4 need priority replenishment review.")
    copilot_service.client = fake

    status, raw = post_json("/api/copilot/query", {"question": "Which products are at risk of stock-out?"})
    body = json.loads(raw)
    check("copilot query returns 200", status == 200)
    check("copilot answer grounded via Gemini",
          body["grounded"] is True and body["ai_status"] == "AVAILABLE" and body["model"] == "fake-model")
    check("copilot answer from fake", body["answer"] == "Chips in store 4 need priority replenishment review.")
    check("copilot intent classified", body["intent"] == "stockout")
    check("copilot analysis date present", body["analysis_date"] == "2026-01-31")
    check("copilot data status sufficient", body["data_status"] == "SUFFICIENT")
    check("copilot evidence present", len(body["evidence"]) > 0 and body["evidence"][0]["type"] == "STOCK_OUT_RISK")
    check("copilot assumptions present", isinstance(body["assumptions"], list) and len(body["assumptions"]) > 0)
    check("gemini actually called", fake.calls == 1)
    check("response never contains the key name",
          "GEMINI_API_KEY" not in raw and "api_key" not in raw and "apiKey" not in raw)

    # Spike intent reaches the spike evidence pipeline
    status, raw = post_json("/api/copilot/query", {"question": "Which products had a sales spike?"})
    body = json.loads(raw)
    check("spike intent routed", status == 200 and body["intent"] == "spike")
    check("spike evidence present", any(e["type"] == "SALES_SPIKE" for e in body["evidence"]))

    # Determinism for identical input
    status, raw_a = post_json("/api/copilot/query", {"question": "What is overstocked?"})
    status, raw_b = post_json("/api/copilot/query", {"question": "What is overstocked?"})
    check("identical questions are deterministic", status == 200 and raw_a == raw_b)

    # ---- Unsupported question ----------------------------------------------
    calls_before = fake.calls
    status, raw = post_json("/api/copilot/query", {"question": "What is the weather in Paris?"})
    body = json.loads(raw)
    check("unsupported question refused", status == 200 and body["intent"] == "unsupported")
    check("unsupported question skips Gemini",
          body["ai_status"] == "SKIPPED" and body["grounded"] is False and body["answer"])
    check("unsupported never reached Gemini", fake.calls == calls_before)

    # ---- Missing key fallback ----------------------------------------------
    no_key = GeminiConfig(api_key=None, model="gemini-2.5-flash")
    copilot_service.client = GeminiClient(no_key)
    status, raw = post_json("/api/copilot/query", {"question": "Which products are at risk of stock-out?"})
    body = json.loads(raw)
    check("missing key falls back", status == 200 and body["ai_status"] == "NOT_CONFIGURED")
    check("missing-key fallback is grounded in engine data",
          body["grounded"] is False and len(body["evidence"]) > 0 and body["answer"])
    check("missing-key response hides config detail", "GEMINI_API_KEY" not in raw)

    # ---- Failure + fallback ------------------------------------------------
    failing = FakeClient()
    failing.generate = lambda system_instruction, user_prompt: (_ for _ in ()).throw(
        GeminiTimeoutError("too slow")
    )
    copilot_service.client = failing
    status, raw = post_json("/api/copilot/query", {"question": "Which products are at risk of stock-out?"})
    body = json.loads(raw)
    check("Gemini timeout falls back", status == 200 and body["ai_status"] == "UNAVAILABLE")
    check("timeout fallback is engine-only",
          body["grounded"] is False and body["grounded"] is False and "engine-only summary" in body["answer"])
    check("timeout error surfaced", body["error"]["code"] == "timeout")

    failing2 = FakeClient()
    failing2.generate = lambda system_instruction, user_prompt: (_ for _ in ()).throw(
        GeminiAPIError("HTTP 429")
    )
    copilot_service.client = failing2
    status, raw = post_json("/api/copilot/query", {"question": "What is overstocked?"})
    body = json.loads(raw)
    check("Gemini API failure falls back", status == 200 and body["ai_status"] == "UNAVAILABLE")
    check("API failure answer still grounded in engine", len(body["evidence"]) > 0)

    # ---- Input validation --------------------------------------------------
    expect_status("/api/copilot/query", "POST", json.dumps({"question": "   "}), 400)
    expect_status("/api/copilot/query", "POST", json.dumps({"question": "x" * 501}), 422)
    expect_status("/api/copilot/query", "POST", json.dumps({}), 422)
    expect_status("/api/copilot/query", "POST", "this is not json", 422)

    # ---- Regression: M1-M3 endpoints still fine ----------------------------
    status, health = get_json("/api/health")
    check("health endpoint intact", status == 200 and health["status"] == "ok")
    status, summary = get_json("/api/data/summary")
    check("data summary intact",
          status == 200 and summary["counts"]["inventory"] == 180 and summary["counts"]["sales"] == 14450)
    status, attention = get_json("/api/analytics/attention-summary")
    check("attention summary intact",
          status == 200 and attention["counts"]["total"] > 0)

    server.should_exit = True
    thread.join(timeout=10)

    if FAILURES:
        print("\nFailures:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nAll copilot API checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())