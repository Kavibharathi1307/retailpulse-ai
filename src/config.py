"""Safe environment-based configuration for RetailPulse AI.

Secrets are read exclusively from environment variables. No API keys are
ever committed to the repository. Missing optional keys fail gracefully
(e.g. the app still starts without GEMINI_API_KEY).
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "retailpulse.db"


def get_env(key: str) -> str | None:
    """Return the value of an environment variable, or None if unset/blank."""
    value = os.environ.get(key)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def get_gemini_api_key() -> str | None:
    """Return the Gemini API key from GEMINI_API_KEY, or None if not set."""
    return get_env("GEMINI_API_KEY")


def gemini_configured() -> bool:
    """True when a Gemini API key is available for future LLM features."""
    return get_gemini_api_key() is not None


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def get_gemini_model() -> str:
    """Return the configured Gemini model name (GEMINI_MODEL env override)."""
    return get_env("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL


DEFAULT_GEMINI_MAX_OUTPUT_TOKENS = 800


def get_gemini_max_output_tokens() -> int:
    """Return the configured max output tokens for Gemini responses."""
    value = get_env("GEMINI_MAX_OUTPUT_TOKENS")
    try:
        parsed = int(value) if value is not None else 0
    except ValueError:
        parsed = 0
    return parsed if parsed > 0 else DEFAULT_GEMINI_MAX_OUTPUT_TOKENS