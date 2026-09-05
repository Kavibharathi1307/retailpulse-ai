"""Deterministic intent classification for the retail copilot (Milestone 4).

Questions are matched against supported retail categories using keyword rules.
No natural-language model is involved: routing must be predictable so that the
same question always maps to the same evidence pipeline. Unsupported questions
are never forwarded to Gemini.
"""

import re

INTENT_STOCKOUT = "stockout"
INTENT_REORDER = "reorder"
INTENT_OVERSTOCK = "overstock"
INTENT_SLOW_MOVERS = "slow_movers"
INTENT_SPIKE = "spike"
INTENT_DROP = "drop"
INTENT_ANOMALY = "anomaly"
INTENT_FORECAST = "forecast"
INTENT_PRODUCT = "product_performance"
INTENT_STORE = "store_performance"
INTENT_ATTENTION = "attention"
INTENT_EXECUTIVE = "executive"
INTENT_UNSUPPORTED = "unsupported"

MAX_PRODUCT_ID = 1000
MAX_STORE_ID = 1000

# Phrases that are clearly outside the retail data domain. Detected first so a
# question like "how is the stock market doing?" is never treated as retail.
# Note: "weather forecast" stays off-topic via the "weather" marker; retail
# demand-forecast questions are routed by the forecast intent below.
OFF_TOPIC_MARKERS = (
    "recipe",
    "cook",
    "weather",
    "salary",
    "who is",
    "capital of",
    "joke",
    "poem",
    "movie",
    "football",
    "stock market",
    "share price",
    "crypto",
    "bitcoin",
    "horoscope",
    "translate",
)

# Priority-ordered (most specific first). Only the first match wins.
_KEYWORD_RULES = [
    # Executive (Milestone 8) is the most general "tell me the big picture"
    # intent, so its phrases are checked before category-specific rules. A
    # question like "which products are declining" becomes an executive signal,
    # while "what is declining in sales" still routes to the sales-drop intent.
    (INTENT_EXECUTIVE, (
        "what should i focus on",
        "where should i take action",
        "where to take action",
        "what are the biggest problems",
        "biggest problems",
        "top opportunities",
        "which products are declining",
        "products are declining",
        "overall retail health",
        "retail health",
        "how healthy",
        "executive summary",
        "executive overview",
        "give me an executive",
        "summarize the",
        "what needs attention",
        "health score",
        "how is the business doing",
        "current retail situation",
        "overview of the",
    )),
    (INTENT_REORDER, (
        "reorder", "re order", "re-order", "restock", "replenish", "order more",
        "should i order", "buy more", "re stock",
    )),
    (INTENT_OVERSTOCK, (
        "overstock", "over stock", "over-stock", "over stocked", "too much stock",
        "excess stock", "surplus", "dead stock",
    )),
    (INTENT_SLOW_MOVERS, (
        "slow moving", "slow-moving", "slow mover", "slowly", "not selling",
        "barely selling", "hardly selling", "low velocity", "dormant",
    )),
    (INTENT_FORECAST, (
        "forecast", "demand outlook", "future demand", "expected demand",
        "next week", "next 7 days", "next 14 days", "next 30 days",
        "rising demand", "falling demand", "rising sales", "falling sales",
        "increasing demand", "decreasing demand", "trending up", "trending down",
        "demand trend", "trend up", "trend down", "how much demand",
        "expect demand", "demand should i expect", "demand for next",
        "inventory enough", "enough inventory", "enough for next",
        "cover the demand", "cover demand", "will i run out",
    )),
    (INTENT_SPIKE, (
        "spike", "surge", "jumped", "shot up", "sold a lot", "went up",
        "sharp increase", "boom", "boost in sales",
    )),
    (INTENT_DROP, (
        "drop", "dropped", "fell", "decline", "declining", "decrease", "decreasing",
        "went down", "slump", "sales going down", "falling", "down trend",
    )),
    (INTENT_ANOMALY, (
        "anomal", "unusual", "abnormal", "outlier", "odd pattern", "suspicious",
    )),
    (INTENT_ATTENTION, (
        "attention", "today", "focus on", "priorit", "what should i look",
        "highlight", "alert", "show me issues", "summary",
    )),
    (INTENT_STOCKOUT, (
        "stock out", "stockout", "stock-out", "running out", "run out",
        "out of stock", "low stock", "low on stock", "low on", "running low",
        "risk", "how much stock left", "inventory level", "empty", "shortage",
    )),
    (INTENT_STORE, ("store", "location", "branch", "outlet")),
    (INTENT_PRODUCT, ("product", "item", "sku", "goods")),
]

# Generic performance phrasing used only when more specific categories missed.
_GENERIC_PERFORMANCE = (
    "performing", "performance", "selling well", "best seller", "top selling",
    "how is", "how are",
)


def _extract_id(question: str, prefixes: tuple[str, ...]) -> int | None:
    for pattern in (
        rf"(?:{'|'.join(prefixes)})\s*#?\s*(\d+)",
        r"\b[pst](\d+)\b",  # p7 / s2 / t3 shorthand
    ):
        for match in re.finditer(pattern, question, flags=re.IGNORECASE):
            value = int(match.group(1))
            return value
    return None


def extract_product_id(question: str) -> int | None:
    value = _extract_id(question, ("product", "item", "sku"))
    if value is not None and 1 <= value <= MAX_PRODUCT_ID:
        return value
    return None


def extract_store_id(question: str) -> int | None:
    value = _extract_id(question, ("store", "location", "branch", "outlet"))
    if value is not None and 1 <= value <= MAX_STORE_ID:
        return value
    return None


def _match_intent(normalized: str) -> str:
    for intent, keywords in _KEYWORD_RULES:
        if any(keyword in normalized for keyword in keywords):
            return intent
    if any(keyword in normalized for keyword in _GENERIC_PERFORMANCE):
        return INTENT_ATTENTION
    return INTENT_UNSUPPORTED


def classify_intent(question: str) -> dict:
    """Return a routing dict for the question (intent + optional ids)."""
    if not question or not question.strip():
        return {
            "intent": INTENT_UNSUPPORTED,
            "product_id": None,
            "store_id": None,
        }
    normalized = re.sub(r"<[^>]+>", " ", question.lower())
    normalized = " ".join(normalized.split()).replace("-", " ")

    if any(marker in normalized for marker in OFF_TOPIC_MARKERS):
        return {
            "intent": INTENT_UNSUPPORTED,
            "product_id": None,
            "store_id": None,
        }

    product_id = extract_product_id(question)
    store_id = extract_store_id(question)
    intent = _match_intent(normalized)

    if intent in (INTENT_PRODUCT, INTENT_STORE) and product_id and intent == INTENT_PRODUCT:
        pass  # product intent keeps its parsed id
    if intent == INTENT_STORE and store_id:
        pass

    return {
        "intent": intent,
        "product_id": product_id,
        "store_id": store_id,
    }