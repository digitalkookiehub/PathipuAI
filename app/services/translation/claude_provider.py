"""Translation with the Claude API. Credentials come from the environment, never from code."""

import logging
from typing import Any

from app.services.translation.base import (
    PermanentProviderError,
    TransientProviderError,
    TranslationRequest,
)
from app.services.translation.prompt import build_system_prompt

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 16000
REQUEST_TIMEOUT_SECONDS = 180.0
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider:
    """Translate with a Claude model; retries are handled by the caller's bounded retry policy."""

    name = "claude"
    is_test = False

    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        self.model = model
        if client is not None:
            self._client = client
            return
        import anthropic  # imported lazily so the app starts without the package when it is not used

        # max_retries=0: the app applies its own bounded retry policy and shows progress while it waits.
        self._client = anthropic.Anthropic(api_key=api_key or None, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)

    def translate(self, request: TranslationRequest) -> str:
        import anthropic

        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=build_system_prompt(request),
                messages=[{"role": "user", "content": request.text}],
                output_config={"effort": "medium"},
                betas=[FALLBACK_BETA],
                fallbacks="default",  # a false-positive safety decline is retried on another model, not a failure
            )
        except anthropic.RateLimitError as exc:
            raise TransientProviderError("The translation service is busy (rate limit).", _retry_after(exc)) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise PermanentProviderError(
                "The translation service rejected the key. Check TRANSLATION_API_KEY in your .env file.", fatal=True
            ) from exc
        except anthropic.NotFoundError as exc:
            raise PermanentProviderError(
                f"The translation model '{self.model}' was not found. Check TRANSLATION_MODEL.", fatal=True
            ) from exc
        except anthropic.BadRequestError as exc:
            raise PermanentProviderError(f"The translation service refused this request: {exc.message}") from exc
        except anthropic.APITimeoutError as exc:
            raise TransientProviderError("The translation service took too long to answer.") from exc
        except anthropic.APIConnectionError as exc:
            raise TransientProviderError(
                "Could not reach the translation service. Check the internet connection."
            ) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code == 429:
                raise TransientProviderError(
                    f"The translation service had a problem ({exc.status_code}).", _retry_after(exc)
                ) from exc
            raise PermanentProviderError(f"The translation service returned an error ({exc.status_code}).") from exc

        if response.stop_reason == "refusal":
            raise PermanentProviderError("The translation service declined to translate this passage.")
        if response.stop_reason == "max_tokens":
            raise PermanentProviderError(
                "This passage was too long to translate in one piece. Lower TRANSLATION_CHUNK_CHARS."
            )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise TransientProviderError("The translation service returned an empty answer.")
        return text


def _retry_after(exc: Any) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None
