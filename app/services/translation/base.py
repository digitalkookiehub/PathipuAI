"""Translation provider interface, so the translation service can be replaced without changing the app."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GlossaryEntry:
    """A glossary term that applies to the text being translated."""

    term: str
    keep_unchanged: bool
    preferred: str | None = None


@dataclass(frozen=True)
class TranslationRequest:
    """One piece of text to translate."""

    text: str
    source_language: str
    target_language: str
    glossary: tuple[GlossaryEntry, ...] = ()
    is_heading: bool = False
    previous_failed: bool = False  # the last answer was not in the target language; the prompt says so


class TransientProviderError(Exception):
    """A temporary problem (rate limit, timeout, server error); the request can be retried."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentProviderError(Exception):
    """A problem retrying will not fix. fatal=True means every later request would fail too (e.g. a bad key)."""

    def __init__(self, message: str, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


class TranslationProvider(Protocol):
    """What the app needs from a translation service."""

    name: str
    is_test: bool

    def translate(self, request: TranslationRequest) -> str:
        """Return the translated text, or raise TransientProviderError / PermanentProviderError."""
        ...
