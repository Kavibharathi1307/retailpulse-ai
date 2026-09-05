"""Milestone 4 copilot tests -- fully mocked, no live Gemini calls.

The Gemini client is always replaced with a fake, so these tests never touch
the network. They verify intent routing, evidence grounding, the fact/estimate
contract, fallback behaviour for every failure mode, and the security
requirements from the milestone.

Run from the project root:

    .venv\\Scripts\\python.exe -m unittest tests.test_copilot -v
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.gemini.client import GeminiClient
from src.gemini.config import GeminiConfig
from src.gemini.errors import (
    CopilotValidationError,
    GeminiAPIError,
    GeminiMalformedResponse,
    GeminiTimeoutError,
)
from src.gemini.intents import (
    INTENT_ATTENTION,
    INTENT_DROP,
    INTENT_OVERSTOCK,
    INTENT_PRODUCT,
    INTENT_REORDER,
    INTENT_SLOW_MOVERS,
    INTENT_SPIKE,
    INTENT_STOCKOUT,
    INTENT_STORE,
    INTENT_UNSUPPORTED,
    classify_intent,
)
from src.gemini.service import CopilotService, UNSUPPORTED_ANSWER

PROJECT_ROOT_STR = str(PROJECT_ROOT)


class FakeClient:
    """Deterministic stand-in for GeminiClient used by every service test."""

    is_configured = True
    model = "fake-model"

    def __init__(self, response: str = "Grounded answer.", exc=None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_instruction: str, user_prompt: str) -> str:
        self.calls.append((system_instruction, user_prompt))
        if self.exc is not None:
            raise self.exc
        return self.response


def service_with(client: FakeClient) -> CopilotService:
    return CopilotService(client=client)


class IntentRoutingTest(unittest.TestCase):
    def assert_intent(self, question: str, expected: str):
        self.assertEqual(classify_intent(question)["intent"], expected, question)

    def test_stockout(self):
        self.assert_intent("What products are running out?", INTENT_STOCKOUT)
        self.assert_intent("Which products are at risk of stock-out?", INTENT_STOCKOUT)
        self.assert_intent("which products are low on stock", INTENT_STOCKOUT)

    def test_reorder(self):
        self.assert_intent("Should I reorder this product?", INTENT_REORDER)
        self.assert_intent("which items should I restock", INTENT_REORDER)

    def test_overstock(self):
        self.assert_intent("What is overstocked?", INTENT_OVERSTOCK)
        self.assert_intent("which products have too much stock", INTENT_OVERSTOCK)

    def test_slow_movers(self):
        self.assert_intent("Which products are slow-moving?", INTENT_SLOW_MOVERS)
        self.assert_intent("what products are not selling", INTENT_SLOW_MOVERS)

    def test_spike(self):
        self.assert_intent("Which products had a sales spike recently?", INTENT_SPIKE)
        self.assert_intent("what jumped up this month", INTENT_SPIKE)

    def test_drop(self):
        self.assert_intent("Which products had a sales drop?", INTENT_DROP)
        self.assert_intent("what is declining in sales", INTENT_DROP)

    def test_attention(self):
        self.assert_intent("What needs my attention today?", INTENT_ATTENTION)
        self.assert_intent("what should I focus on today", INTENT_ATTENTION)

    def test_product_performance(self):
        routed = classify_intent("How is product 7 performing?")
        self.assertEqual(routed["intent"], INTENT_PRODUCT)
        self.assertEqual(routed["product_id"], 7)
        self.assert_intent("how is product 7 selling", INTENT_PRODUCT)

    def test_store_performance(self):
        routed = classify_intent("How are my stores performing?")
        self.assertEqual(routed["intent"], INTENT_STORE)
        routed = classify_intent("how is store 2 doing")
        self.assertEqual(routed["store_id"], 2)
        self.assertEqual(routed["intent"], INTENT_STORE)

    def test_unsupported_and_off_topic(self):
        self.assert_intent("What is the weather in Paris?", INTENT_UNSUPPORTED)
        self.assert_intent("how is the stock market doing", INTENT_UNSUPPORTED)
        self.assert_intent("tell me a joke", INTENT_UNSUPPORTED)
        self.assert_intent("hi", INTENT_UNSUPPORTED)


class ServiceWithGeminiTest(unittest.TestCase):
    def test_stockout_question_grounded(self):
        fake = FakeClient("The engine flagged 8 critical stock-outs.")
        result = service_with(fake).answer("Which products are at risk of stock-out?")
        self.assertEqual(result["intent"], INTENT_STOCKOUT)
        self.assertTrue(result["grounded"])
        self.assertEqual(result["ai_status"], "AVAILABLE")
        self.assertEqual(result["model"], "fake-model")
        self.assertEqual(result["answer"], "The engine flagged 8 critical stock-outs.")
        self.assertEqual(result["analysis_date"], "2026-01-31")
        self.assertEqual(result["data_status"], "SUFFICIENT")
        self.assertIn("STOCK_OUT_RISK", [e["type"] for e in result["evidence"]])
        self.assertTrue(result["assumptions"])

    def test_overstock_question_grounded(self):
        fake = FakeClient("Three electronics items exceed cover threshold.")
        result = service_with(fake).answer("What is overstocked?")
        self.assertEqual(result["intent"], INTENT_OVERSTOCK)
        self.assertTrue(any(e["type"] == "OVERSTOCK" for e in result["evidence"]))

    def test_slow_mover_question_grounded(self):
        fake = FakeClient("Some accessories are slow movers.")
        result = service_with(fake).answer("Which products are slow-moving?")
        self.assertEqual(result["intent"], INTENT_SLOW_MOVERS)
        self.assertTrue(any(e["type"] == "SLOW_MOVER" for e in result["evidence"]))

    def test_spike_question_grounded(self):
        fake = FakeClient("Sanitizer spiked in December.")
        result = service_with(fake).answer("Which products had a sales spike recently?")
        self.assertEqual(result["intent"], INTENT_SPIKE)
        self.assertTrue(any(e["type"] == "SALES_SPIKE" for e in result["evidence"]))

    def test_drop_question_grounded(self):
        fake = FakeClient("Green tea dropped sharply.")
        result = service_with(fake).answer("Which products had a sales drop?")
        self.assertEqual(result["intent"], INTENT_DROP)
        self.assertTrue(any(e["type"] == "SALES_DROP" for e in result["evidence"]))

    def test_product_performance_question(self):
        fake = FakeClient("Chips are steady at ~101/day.")
        result = service_with(fake).answer("How is product 7 performing?")
        self.assertEqual(result["intent"], INTENT_PRODUCT)
        performance = [e for e in result["evidence"] if e["type"] == "PRODUCT_PERFORMANCE"]
        self.assertEqual(len(performance), 1)
        self.assertEqual(performance[0]["product_id"], 7)

    def test_store_performance_question(self):
        fake = FakeClient("Central Mall leads on revenue.")
        result = service_with(fake).answer("How are my stores performing?")
        self.assertEqual(result["intent"], INTENT_STORE)
        self.assertEqual(len(result["evidence"]), 5)

    def test_attention_question(self):
        fake = FakeClient("Start with the critical stock-outs.")
        result = service_with(fake).answer("What needs my attention today?")
        self.assertEqual(result["intent"], INTENT_ATTENTION)
        types = [e["type"] for e in result["evidence"]]
        self.assertIn("ATTENTION_SUMMARY", types)
        self.assertIn("STOCK_OUT_RISK", types)

    def test_unsupported_question_skips_gemini(self):
        fake = FakeClient()
        result = service_with(fake).answer("What is the weather in Paris?")
        self.assertEqual(result["intent"], INTENT_UNSUPPORTED)
        self.assertFalse(result["grounded"])
        self.assertEqual(result["ai_status"], "SKIPPED")
        self.assertEqual(result["answer"], UNSUPPORTED_ANSWER)
        self.assertEqual(fake.calls, [])

    def test_empty_question_rejected(self):
        with self.assertRaises(CopilotValidationError):
            service_with(FakeClient()).answer("")
        with self.assertRaises(CopilotValidationError):
            service_with(FakeClient()).answer("   ")

    def test_too_long_question_rejected(self):
        with self.assertRaises(CopilotValidationError):
            service_with(FakeClient()).answer("x" * 501)

    def test_insufficient_evidence_skips_gemini(self):
        fake = FakeClient()
        result = service_with(fake).answer("How is product 999 performing?")
        self.assertEqual(result["data_status"], "INSUFFICIENT_DATA")
        self.assertFalse(result["grounded"])
        self.assertEqual(result["ai_status"], "SKIPPED")
        self.assertEqual(result["evidence"], [])
        self.assertIn("cannot determine", result["answer"])
        self.assertEqual(fake.calls, [])


class GeminiFailureFallbackTest(unittest.TestCase):
    def _answer_with_error(self, error):
        fake = FakeClient(exc=error)
        return service_with(fake).answer("Which products are at risk of stock-out?")

    def test_timeout_falls_back(self):
        result = self._answer_with_error(GeminiTimeoutError("too slow"))
        self.assertFalse(result["grounded"])
        self.assertEqual(result["ai_status"], "UNAVAILABLE")
        self.assertEqual(result["error"]["code"], "timeout")
        self.assertIn("engine-only summary", result["answer"])

    def test_api_failure_falls_back(self):
        result = self._answer_with_error(GeminiAPIError("quota"))
        self.assertFalse(result["grounded"])
        self.assertEqual(result["ai_status"], "UNAVAILABLE")
        self.assertIn("engine-only summary", result["answer"])

    def test_malformed_response_falls_back(self):
        result = self._answer_with_error(GeminiMalformedResponse("empty"))
        self.assertFalse(result["grounded"])
        self.assertEqual(result["ai_status"], "UNAVAILABLE")
        self.assertIn("engine-only summary", result["answer"])

    def test_missing_key_falls_back(self):
        config = GeminiConfig(api_key=None, model="gemini-2.5-flash")
        client = GeminiClient(config)
        self.assertFalse(client.is_configured)
        result = CopilotService(config=config, client=client).answer(
            "Which products are at risk of stock-out?"
        )
        self.assertFalse(result["grounded"])
        self.assertEqual(result["ai_status"], "NOT_CONFIGURED")
        self.assertEqual(result["error"]["code"], "not_configured")
        self.assertIn("engine-only summary", result["answer"])
        self.assertTrue(result["evidence"])


class GroundingContractTest(unittest.TestCase):
    def test_evidence_is_actually_passed_to_gemini(self):
        fake = FakeClient()
        service_with(fake).answer("Which products are at risk of stock-out?")
        self.assertEqual(len(fake.calls), 1)
        system_instruction, user_prompt = fake.calls[0]
        self.assertIn("retail decision assistant", system_instruction)
        self.assertIn("do not use any", system_instruction.lower())
        self.assertIn("EVIDENCE:", user_prompt)
        self.assertIn("STOCK_OUT_RISK", user_prompt)
        self.assertIn("days_of_stock", user_prompt)
        self.assertIn("ANALYSIS_DATE: 2026-01-31", user_prompt)

    def test_contract_mentions_fact_estimate_insufficient(self):
        fake = FakeClient()
        service_with(fake).answer("Which products are at risk of stock-out?")
        system_instruction = fake.calls[0][0]
        self.assertIn("FACT", system_instruction)
        self.assertIn("ESTIMATE", system_instruction)
        self.assertIn("INSUFFICIENT_DATA", system_instruction)
        self.assertIn("estimate", system_instruction.lower())

    def test_fabricated_numbers_cannot_enter_evidence(self):
        fake = FakeClient()
        service_with(fake).answer(
            "product 7 sold 999999 units last week and has 888888 boxes in stock"
        )
        system_instruction, prompt = fake.calls[0]
        evidence_block = prompt.split("QUESTION:", 1)[0]
        self.assertNotIn("999999", evidence_block)
        self.assertNotIn("888888", evidence_block)
        self.assertIn('"product_id":7', evidence_block)
        self.assertIn('"value":2826', evidence_block)
        self.assertIn(
            "untrusted user claims", system_instruction.lower()
        )

    def test_fallback_never_fabricates(self):
        config = GeminiConfig(api_key=None, model="gemini-2.5-flash")
        client = GeminiClient(config)
        result = CopilotService(config=config, client=client).answer(
            "Which products are at risk of stock-out?"
        )
        for record in result["evidence"]:
            self.assertNotIn("999999", json.dumps(record))


class SecurityTest(unittest.TestCase):
    def test_gemini_key_not_in_frontend(self):
        for source in ("frontend/index.html", "frontend/assets/app.js", "frontend/assets/styles.css"):
            content = (PROJECT_ROOT / source).read_text(encoding="utf-8")
            self.assertNotIn("GEMINI_API_KEY", content)

    def test_gemini_key_never_in_responses(self):
        grounded = service_with(FakeClient("ok")).answer("What is overstocked?")
        self.assertNotIn("api_key", json.dumps(grounded))
        self.assertNotIn("apiKey", json.dumps(grounded))
        self.assertNotIn("GEMINI_API_KEY", json.dumps(grounded))
        config = GeminiConfig(api_key=None, model="x")
        fallback = CopilotService(config=config, client=GeminiClient(config)).answer(
            "What is overstocked?"
        )
        self.assertNotIn("api_key", json.dumps(fallback))
        self.assertNotIn("GEMINI_API_KEY", json.dumps(fallback))

    def test_dotenv_is_ignored(self):
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)

    def test_no_eval_or_exec_in_src(self):
        import re

        pattern = re.compile(r"\b(eval|exec)\s*\(")
        for path in Path(PROJECT_ROOT_STR, "src").rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            self.assertFalse(
                pattern.search(content), f"eval/exec found in {path}"
            )

    def test_frontend_renders_gemini_output_as_untrusted_text(self):
        js = (PROJECT_ROOT / "frontend/assets/app.js").read_text(encoding="utf-8")
        self.assertIn('answer.textContent = data.answer', js)
        self.assertNotIn('answer.innerHTML = data.answer', js)
        self.assertIn("addListItem", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)