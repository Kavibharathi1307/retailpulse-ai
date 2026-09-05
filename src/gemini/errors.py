"""Gemini integration error types (Milestone 4).

Each failure mode is mapped to a distinct exception so the copilot service can
decide between a graceful deterministic fallback and a hard error. No API key,
prompt, or raw exception detail ever crosses these boundaries.
"""


class GeminiError(Exception):
    """Base class for every Gemini integration failure."""


class GeminiNotConfigured(GeminiError):
    """GEMINI_API_KEY is absent; the service must fall back deterministically."""


class GeminiTimeoutError(GeminiError):
    """The model call exceeded the configured timeout."""


class GeminiAPIError(GeminiError):
    """The model call failed (invalid key, quota, network, etc.)."""


class GeminiMalformedResponse(GeminiError):
    """The model returned an empty or unparseable response."""


class CopilotValidationError(ValueError):
    """The question itself is invalid (empty or too long)."""