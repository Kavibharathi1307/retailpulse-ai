"""Live smoke test against a real `python app.py` process (no key required)."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main() -> int:
    server = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    try:
        ready = False
        for _ in range(30):
            time.sleep(0.5)
            try:
                status, _ = get("/api/health")
                if status == 200:
                    ready = True
                    break
            except Exception:
                continue
        if not ready:
            print("FAIL server did not become ready")
            return 1

        status, raw = get("/api/health")
        health = json.loads(raw)
        print(f"[{'PASS' if status == 200 and health['status'] == 'ok' else 'FAIL'}] /api/health status ok, "
              f"gemini_configured={health.get('gemini_configured')}")

        status, html = get("/")
        print(f"[{'PASS' if status == 200 and 'id=\"copilot-form\"' in html else 'FAIL'}] / serves copilot frontend")

        status, att = post("/api/copilot/query", {"question": "Which products are at risk of stock-out?"})
        ok = (
            status == 200
            and att["intent"] == "stockout"
            and att["data_status"] == "SUFFICIENT"
            and len(att["evidence"]) > 0
            and att["answer"]
        )
        print(f"[{'PASS' if ok else 'FAIL'}] stockout question answered | grounded={att['grounded']} "
              f"ai_status={att['ai_status']} evidence={len(att['evidence'])} intents_snippet={att['answer'][:60]!r}")

        status, unsup = post("/api/copilot/query", {"question": "what is the weather today"})
        ok = status == 200 and unsup["intent"] == "unsupported" and unsup["ai_status"] == "SKIPPED"
        print(f"[{'PASS' if ok else 'FAIL'}] unsupported refused gracefully")

        status, perf = post("/api/copilot/query", {"question": "How is product 7 performing?"})
        ok = status == 200 and perf["intent"] == "product_performance"
        print(f"[{'PASS' if ok else 'FAIL'}] product performance intent routed")

        # Regression on M1-M3 endpoints over the running app
        status, dsum = get("/api/data/summary")
        summary = json.loads(dsum)
        print(f"[{'PASS' if status == 200 and summary['counts']['sales'] == 14450 else 'FAIL'}] data summary intact")
        status, sinv = get("/api/inventory")
        inv = json.loads(sinv)
        print(f"[{'PASS' if status == 200 and inv['total'] == 180 else 'FAIL'}] inventory endpoint intact")

        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())