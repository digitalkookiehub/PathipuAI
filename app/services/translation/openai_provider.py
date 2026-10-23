"""Translation with the OpenAI API. Credentials come from the environment, never from code."""

import logging
from typing import Any

from app.services.translation.base import (
    PermanentProviderError,
    TransientProviderError,
    TranslationRequest,
)
from app.services.translation.prompt import build_system_prompt

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 180.0


class OpenAIProvider:
    """Translate with an OpenAI chat model; retries are handled by the caller's bounded retry policy."""

    name = "openai"
    is_test = False

    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        self.model = model
        if client is not None:
            self._client = client
            return
        import openai  # imported lazily so the app starts without the package when it is not used

        # max_retries=0: the app applies its own bounded retry policy and shows progress while it waits.
        self._client = openai.OpenAI(api_key=api_key or None, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)

    def translate(self, request: TranslationRequest) -> str:
        import openai

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": build_system_prompt(request)},
                    {"role": "user", "content": request.text},
                ],
            )
        except openai.RateLimitError as exc:
            if getattr(exc, "code", None) == "insufficient_quota":
                raise PermanentProviderError(
                    "Your OpenAI account has no credit left. Add credit under Billing on the OpenAI website.",
                    fatal=True,
                ) from exc
            raise TransientProviderError("The translation service is busy (rate limit).", _retry_after(exc)) from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise PermanentProviderError(
                "The translation service rejected the key. Check TRANSLATION_API_KEY in your .env file.", fatal=True
            ) from exc
        except openai.NotFoundError as exc:
            raise PermanentProviderError(
                f"The translation model '{self.model}' was not found for your account. Check TRANSLATION_MODEL.",
                fatal=True,
            ) from exc
        except openai.BadRequestError as exc:
            raise PermanentProviderError(f"The translation service refused this request: {exc.message}") from exc
        except openai.APITimeoutError as exc:
            raise TransientProviderError("The translation service took too long to answer.") from exc
        except openai.APIConnectionError as exc:
            raise TransientProviderError(
                "Could not reach the translation service. Check the internet connection."
            ) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code == 429:
                raise TransientProviderError(
                    f"The translation service had a problem ({exc.status_code}).", _retry_after(exc)
                ) from exc
            raise PermanentProviderError(f"The translation service returned an error ({exc.status_code}).") from exc

        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise PermanentProviderError("The translation service declined to translate this passage.")
        if choice.finish_reason == "content_filter":
            raise PermanentProviderError("The translation service's content filter blocked this passage.")
        if choice.finish_reason == "length":
            raise PermanentProviderError(
                "This passage was too long to translate in one piece. Lower TRANSLATION_CHUNK_CHARS."
            )
        text = (choice.message.content or "").strip()
        if not text:
            raise TransientProviderError("The translation service returned an empty answer.")
        return text


def _retry_after(exc: Any) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None
