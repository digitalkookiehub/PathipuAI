"""Placeholder translator for local testing. It does not translate; it only marks the text clearly."""

from app.config import SUPPORTED_LANGUAGES
from app.services.translation.base import TranslationRequest


class MockProvider:
    """Returns the source text prefixed with a test marker, keeping paragraphs and glossary terms intact."""

    name = "mock"
    is_test = True

    def translate(self, request: TranslationRequest) -> str:
        target = SUPPORTED_LANGUAGES.get(request.target_language, (request.target_language,))[0]
        marker = f"[{target} test translation] "
        if request.is_heading:
            return marker + request.text
        return "\n\n".join(marker + paragraph for paragraph in request.text.split("\n\n"))
