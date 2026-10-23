"""Translation providers and chunking."""

import importlib.util
import os
from dataclasses import dataclass

from app.config import Settings
from app.services.translation.base import TranslationProvider
from app.services.translation.claude_provider import ClaudeProvider
from app.services.translation.mock import MockProvider
from app.services.translation.openai_provider import OpenAIProvider

# Used when TRANSLATION_MODEL is not set. Model names change; set TRANSLATION_MODEL to choose another.
DEFAULT_MODELS = {"claude": "claude-opus-5-5", "openai": "gpt-5.4-mini"}
PROVIDER_PACKAGES = {"claude": "anthropic", "openai": "openai"}
PROVIDER_LABELS = {"claude": "Claude", "openai": "OpenAI"}
PROVIDER_ENV_KEYS = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


class ProviderSetupError(Exception):
    """The configured translation provider cannot be used; the message is safe to show the author."""


@dataclass(frozen=True)
class ProviderStatus:
    """Whether translation can run, and in what mode."""

    name: str
    label: str
    ready: bool
    message: str | None
    is_test: bool
    model: str | None


def resolved_model(settings: Settings) -> str:
    """The model to use: TRANSLATION_MODEL if set, otherwise the provider's default."""
    return settings.translation_model or DEFAULT_MODELS.get(settings.translation_provider, "")


def provider_status(settings: Settings) -> ProviderStatus:
    """Describe the configured provider without contacting it."""
    name = settings.translation_provider
    if name == "mock":
        return ProviderStatus(
            "mock",
            "Test mode",
            True,
            "Test mode: translations are placeholders, not real translations. "
            "Set TRANSLATION_PROVIDER=openai (or claude) and TRANSLATION_API_KEY in .env for real translation.",
            True,
            None,
        )
    if name in PROVIDER_PACKAGES:
        model = resolved_model(settings)
        label = f"{PROVIDER_LABELS[name]} ({model})"
        if importlib.util.find_spec(PROVIDER_PACKAGES[name]) is None:
            message = f"The '{PROVIDER_PACKAGES[name]}' package is not installed."
            return ProviderStatus(name, label, False, message, False, model)
        if not (settings.translation_api_key or os.getenv(PROVIDER_ENV_KEYS[name])):
            return ProviderStatus(
                name, label, False, "Add TRANSLATION_API_KEY to your .env file to translate.", False, model
            )
        return ProviderStatus(name, label, True, None, False, model)
    message = f"Unknown translation provider '{name}'. Use 'mock', 'openai' or 'claude'."
    return ProviderStatus(name, name, False, message, False, None)


def get_provider(settings: Settings) -> TranslationProvider:
    """Create the configured provider or raise ProviderSetupError with a friendly message."""
    status = provider_status(settings)
    if not status.ready:
        raise ProviderSetupError(status.message or "Translation is not set up.")
    if status.name == "mock":
        return MockProvider()
    model = resolved_model(settings)
    if status.name == "openai":
        return OpenAIProvider(settings.translation_api_key, model)
    return ClaudeProvider(settings.translation_api_key, model)
