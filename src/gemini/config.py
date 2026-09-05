"""Gemini client configuration (Milestone 4).

Single source of truth for what is sent to the Gemini API. The API key flows
from the environment only; everything else has safe defaults and can be tuned
through environment variables.
"""

from dataclasses import dataclass

from src.config import (
    get_gemini_api_key,
    get_gemini_max_output_tokens,
    get_gemini_model,
)


@dataclass(frozen=True)
class GeminiConfig:
    """Runtime settings for the Gemini client.

    ``api_key`` is never logged, printed, or serialised.
    """

    api_key: str | None
    model: str
    temperature: float = 0.2
    max_output_tokens: int = 800
    timeout_seconds: float = 30.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def load_gemini_config() -> GeminiConfig:
    """Build a config from the environment, failing gracefully when no key."""
    return GeminiConfig(
        api_key=get_gemini_api_key(),
        model=get_gemini_model(),
        max_output_tokens=get_gemini_max_output_tokens(),
    )