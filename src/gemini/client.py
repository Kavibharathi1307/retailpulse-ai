"""Thin, replaceable wrapper around the Google Gemini Python SDK.

The client keeps the SDK behind one interface so tests can substitute a fake
and the rest of the application never imports ``google.genai`` directly.
Timeouts and API failures are normalised into the error types defined in
``errors.py``.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from src.gemini.config import GeminiConfig, load_gemini_config
from src.gemini.errors import (
    GeminiAPIError,
    GeminiMalformedResponse,
    GeminiNotConfigured,
    GeminiTimeoutError,
)


class GeminiClient:
    """Wrapper around ``google.genai.Client`` with safe error mapping."""

    def __init__(self, config: GeminiConfig | None = None):
        self.config = config or load_gemini_config()
        self._sdk_client = None
        self._executor = ThreadPoolExecutor(max_workers=2)

    @property
    def is_configured(self) -> bool:
        return self.config.configured

    @property
    def model(self) -> str:
        return self.config.model

    def _ensure_sdk_client(self):
        if self._sdk_client is None:
            from google import genai

            self._sdk_client = genai.Client(api_key=self.config.api_key)
        return self._sdk_client

    def generate(self, system_instruction: str, user_prompt: str) -> str:
        """Return the model's text answer or raise a GeminiError on failure."""
        if not self.config.configured:
            raise GeminiNotConfigured("Gemini is not configured (missing API key).")

        sdk = self._ensure_sdk_client()

        def _call():
            from google.genai import types

            response = sdk.models.generate_content(
                model=self.config.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_output_tokens,
                ),
            )
            return self._extract_text(response)

        try:
            return self._executor.submit(_call).result(timeout=self.config.timeout_seconds)
        except FutureTimeout:
            raise GeminiTimeoutError(
                f"Gemini call timed out after {self.config.timeout_seconds:g}s."
            ) from None
        except GeminiError:
            raise
        except Exception as exc:  # SDK/network/quota errors are mapped generically
            raise GeminiAPIError(f"Gemini API call failed ({type(exc).__name__}).") from exc

    @staticmethod
    def _extract_text(response) -> str:
        try:
            text = response.text
        except (AttributeError, IndexError, TypeError):
            text = None
        if text is None or not str(text).strip():
            raise GeminiMalformedResponse("Gemini returned an empty response.")
        return str(text).strip()