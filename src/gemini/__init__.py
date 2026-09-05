"""Gemini-grounded retail copilot (Milestone 4).

Exposes the service, client, config, and error types used by the API layer and
tests. Integration is fully replaceable: nothing outside this package talks to
the Gemini SDK directly.
"""

from src.gemini.client import GeminiClient
from src.gemini.config import GeminiConfig, load_gemini_config
from src.gemini.errors import (
    CopilotValidationError,
    GeminiAPIError,
    GeminiError,
    GeminiMalformedResponse,
    GeminiNotConfigured,
    GeminiTimeoutError,
)
from src.gemini.intents import classify_intent, extract_product_id, extract_store_id
from src.gemini.service import CopilotService

__all__ = [
    "CopilotService",
    "GeminiClient",
    "GeminiConfig",
    "load_gemini_config",
    "classify_intent",
    "extract_product_id",
    "extract_store_id",
    "CopilotValidationError",
    "GeminiError",
    "GeminiAPIError",
    "GeminiMalformedResponse",
    "GeminiNotConfigured",
    "GeminiTimeoutError",
]