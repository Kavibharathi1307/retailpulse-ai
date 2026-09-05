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