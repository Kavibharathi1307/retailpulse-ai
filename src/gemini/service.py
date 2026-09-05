"""Copilot orchestration: question -> intent -> evidence -> Gemini -> answer.

The service owns the full grounded flow and enforces the security boundary:
* intent classification decides what to answer (never Gemini);
* evidence comes ONLY from the deterministic analytics engine;
* Gemini only rewrites that evidence into natural language;
* every Gemini failure mode falls back to a deterministic summary so the
  application stays usable even when the API is unavailable.
"""

from src.gemini.client import GeminiClient
from src.gemini.config import GeminiConfig, load_gemini_config
from src.gemini.errors import (
    CopilotValidationError,
    GeminiError,
    GeminiNotConfigured,
    GeminiTimeoutError,
)
from src.gemini.evidence import build_evidence
from src.gemini.intents import INTENT_FORECAST, INTENT_UNSUPPORTED, classify_intent
from src.gemini.prompts import SYSTEM_INSTRUCTION, build_user_prompt

MAX_QUESTION_LENGTH = 500

UNSUPPORTED_ANSWER = (
    "I can answer questions about the available sales and inventory data, "
    "but I don't have enough data to answer that question."
)


class CopilotService:
    """High-level copilot facade used by the API layer."""

    def __init__(
        self,
        config: GeminiConfig | None = None,
        client: GeminiClient | None = None,
    ):
        self.config = config or load_gemini_config()
        self.client = client or GeminiClient(self.config)

    # ------------------------------------------------------------------ API

    def answer(self, question: str) -> dict:
        """Produce a grounded answer response for a natural-language question."""
        question = (question or "").strip()
        if not question:
            raise CopilotValidationError("question must not be empty")
        if len(question) > MAX_QUESTION_LENGTH:
            raise CopilotValidationError(
                f"question must not exceed {MAX_QUESTION_LENGTH} characters"
            )

        routing = classify_intent(question)
        intent = routing["intent"]

        if intent == INTENT_UNSUPPORTED:
            return {
                "question": question,
                "answer": UNSUPPORTED_ANSWER,
                "intent": intent,
                "analysis_date": None,
                "data_status": "UNSUPPORTED",
                "evidence": [],
                "assumptions": [],
                "grounded": False,
                "ai_status": "SKIPPED",
            }

        evidence_bundle = build_evidence(
            intent=intent,
            product_id=routing["product_id"],
            store_id=routing["store_id"],
        )
        evidence = evidence_bundle["evidence"]
        analysis_date = evidence_bundle["analysis_date"]
        data_status = evidence_bundle["data_status"]
        assumptions = self._assumptions(analysis_date)

        if not evidence:
            if intent == INTENT_FORECAST:
                answer_text = "Insufficient historical data for a reliable forecast."
            else:
                answer_text = (
                    "The available sales and inventory data cannot determine the "
                    "answer to that question."
                )
            return {
                "question": question,
                "answer": answer_text,
                "intent": intent,
                "analysis_date": analysis_date,
                "data_status": data_status,
                "evidence": [],
                "assumptions": assumptions,
                "grounded": False,
                "ai_status": "SKIPPED",
            }

        if not self.client.is_configured:
            return self._fallback(
                question=question,
                intent=intent,
                analysis_date=analysis_date,
                data_status=data_status,
                evidence=evidence,
                assumptions=assumptions,
                ai_status="NOT_CONFIGURED",
                error={"code": "not_configured", "message": "Gemini is not configured."},
            )

        user_prompt = build_user_prompt(
            question=question,
            evidence=evidence,
            analysis_date=analysis_date,
            data_status=data_status,
            intent=intent,
        )

        try:
            answer = self.client.generate(SYSTEM_INSTRUCTION, user_prompt)
        except GeminiNotConfigured:
            return self._fallback(
                question, intent, analysis_date, data_status, evidence, assumptions,
                ai_status="NOT_CONFIGURED",
                error={"code": "not_configured", "message": "Gemini is not configured."},
            )
        except GeminiTimeoutError:
            return self._fallback(
                question, intent, analysis_date, data_status, evidence, assumptions,
                ai_status="UNAVAILABLE",
                error={"code": "timeout", "message": "Gemini did not respond in time."},
            )
        except GeminiError as exc:
            code = type(exc).__name__.replace("Gemini", "").replace("Error", "").lower()
            return self._fallback(
                question, intent, analysis_date, data_status, evidence, assumptions,
                ai_status="UNAVAILABLE",
                error={"code": f"gemini_{code}", "message": str(exc) or "Gemini is unavailable."},
            )

        return {
            "question": question,
            "answer": answer,
            "intent": intent,
            "analysis_date": analysis_date,
            "data_status": data_status,
            "evidence": evidence,
            "assumptions": assumptions,
            "grounded": True,
            "ai_status": "AVAILABLE",
            "model": self.client.model,
        }

    # ------------------------------------------------------- deterministic

    def _fallback(
        self,
        question: str,
        intent: str,
        analysis_date: str,
        data_status: str,
        evidence: list,
        assumptions: list,
        ai_status: str,
        error: dict,
    ) -> dict:
        """Deterministic evidence summary used when Gemini cannot answer."""
        return {
            "question": question,
            "answer": self._summarize(intent, evidence, analysis_date),
            "intent": intent,
            "analysis_date": analysis_date,
            "data_status": data_status,
            "evidence": evidence,
            "assumptions": assumptions,
            "grounded": False,
            "ai_status": ai_status,
            "error": error,
        }

    @staticmethod
    def _summarize(intent: str, evidence: list[dict], analysis_date: str) -> str:
        lines = [
            f"Deterministic analytics summary as of {analysis_date}:",
        ]
        if intent in ("stockout", "reorder"):
            critical = [e for e in evidence if e.get("severity") == "CRITICAL"]
            lines.append(
                f"  Stock-out risk: {len([e for e in evidence if e.get('type') == 'STOCK_OUT_RISK'])} "
                f"matching records, {len(critical)} at CRITICAL severity."
            )
        elif intent == "overstock":
            lines.append(f"  Overstock: {len(evidence)} item(s) exceed the cover threshold.")
        elif intent == "slow_movers":
            lines.append(f"  Slow movers: {len(evidence)} item(s) below the velocity threshold.")
        elif intent in ("spike", "drop", "anomaly"):
            lines.append(f"  Sales anomalies selected: {len(evidence)} record(s).")
        elif intent in ("product_performance", "store_performance"):
            lines.append(f"  Performance records selected: {len(evidence)}.")
        elif intent == "forecast":
            summary = next((e for e in evidence if e.get("type") == "FORECAST_SUMMARY"), None)
            if summary and summary.get("value"):
                value = summary["value"]
                horizon = summary.get("horizon_days")
                lines.append(
                    f"  Demand outlook: {value.get('rising_demand', 0)} rising, "
                    f"{value.get('falling_demand', 0)} falling demand; "
                    f"{value.get('inventory_at_risk', 0)} item(s) may not cover "
                    f"expected {horizon}-day demand."
                )
        elif intent == "attention":
            counts = next((e for e in evidence if e.get("type") == "ATTENTION_SUMMARY"), None)
            if counts and counts.get("value"):
                value = counts["value"]
                lines.append(
                    f"  Attention counts: {value.get('total', 0)} issues "
                    f"({value.get('stock_out_risks', 0)} stock-out, "
                    f"{value.get('overstock', 0)} overstock, "
                    f"{value.get('slow_movers', 0)} slow movers, "
                    f"{value.get('sales_spikes', 0)} spikes, "
                    f"{value.get('sales_drops', 0)} drops)."
                )

        for item in evidence[:5]:
            name = item.get("product_name") or item.get("store_name") or item.get("type")
            location = f" (store {item.get('store_id')})" if item.get("store_id") else ""
            lines.append(f"  - {name}{location}: {item.get('metric')} = {item.get('value')}")

        if not evidence:
            lines.append("  No matching records were found in the retail data.")
        lines.append("Note: Gemini is unavailable, so this is an engine-only summary.")
        return "\n".join(lines)

    @staticmethod
    def _assumptions(analysis_date: str) -> list[str]:
        return [
            f"Analysis is based on the committed retail dataset as of {analysis_date}.",
            "Facts come from RetailPulse's deterministic analytics engine; Gemini only "
            "phrases the answer from the supplied evidence.",
            "Stock-out dates are deterministic estimates based on the 28-day average "
            "daily sales rate, not guarantees.",
            "Demand forecasts are deterministic estimates based on recent demand "
            "history and are not guarantees of future sales.",
            "Profitability cannot be assessed because cost/margin data is unavailable.",
            "Evidence is limited to the most relevant records.",
        ]