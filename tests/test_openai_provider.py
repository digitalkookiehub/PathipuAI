import dataclasses
from types import SimpleNamespace

import pytest

from app.services.translation import (
    ProviderSetupError,
    get_provider,
    provider_status,
    resolved_model,
)
from app.services.translation.base import (
    PermanentProviderError,
    TransientProviderError,
    TranslationRequest,
)
from app.services.translation.openai_provider import OpenAIProvider

openai = pytest.importorskip("openai")
httpx = pytest.importorskip("httpx")

REQUEST = TranslationRequest(text="வணக்கம்", source_language="ta", target_language="te")


def http_response(status, headers=None):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return httpx.Response(status, request=request, headers=headers or {})


def api_error(cls, status, headers=None, body=None):
    return cls("problem", response=http_response(status, headers), body=body)


class FakeClient:
    """Stands in for openai.OpenAI: records the request and returns or raises what it is told to."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def reply(content="నమస్కారం", finish_reason="stop", refusal=None):
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason, message=message)])


def provider_for(outcome):
    client = FakeClient(outcome)
    return OpenAIProvider("key", "gpt-5.4-mini", client=client), client


def test_translates_with_the_expected_request():
    provider, client = provider_for(reply("  నమస్కారం  "))
    assert provider.translate(REQUEST) == "నమస్కారం"
    call = client.calls[0]
    assert call["model"] == "gpt-5.4-mini"
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    assert call["messages"][1]["content"] == "வணக்கம்"
    assert "from Tamil into Telugu" in call["messages"][0]["content"]
    for unsupported_on_some_models in ("temperature", "max_tokens", "top_p"):
        assert unsupported_on_some_models not in call


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (reply("x", refusal="I cannot help with that"), "declined"),
        (reply("x", finish_reason="content_filter"), "content filter"),
        (reply("x", finish_reason="length"), "too long"),
    ],
)
def test_unusable_answers_are_permanent_errors(outcome, message):
    provider, _ = provider_for(outcome)
    with pytest.raises(PermanentProviderError, match=message) as caught:
        provider.translate(REQUEST)
    assert caught.value.fatal is False


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_answer_is_retried(empty):
    provider, _ = provider_for(reply(empty))
    with pytest.raises(TransientProviderError, match="empty"):
        provider.translate(REQUEST)


@pytest.mark.parametrize(
    ("make_error", "expected"),
    [
        (lambda: api_error(openai.RateLimitError, 429, {"retry-after": "7"}), ("transient", 7.0)),
        (lambda: api_error(openai.RateLimitError, 429, body={"code": "rate_limit_exceeded"}), ("transient", None)),
        (lambda: api_error(openai.InternalServerError, 500), ("transient", None)),
        (lambda: api_error(openai.APIStatusError, 503), ("transient", None)),
        (lambda: openai.APITimeoutError(request=httpx.Request("POST", "https://x")), ("transient", None)),
        (lambda: openai.APIConnectionError(request=httpx.Request("POST", "https://x")), ("transient", None)),
        (lambda: api_error(openai.RateLimitError, 429, body={"code": "insufficient_quota"}), ("fatal", None)),
        (lambda: api_error(openai.AuthenticationError, 401), ("fatal", None)),
        (lambda: api_error(openai.PermissionDeniedError, 403), ("fatal", None)),
        (lambda: api_error(openai.NotFoundError, 404), ("fatal", None)),
        (lambda: api_error(openai.BadRequestError, 400), ("permanent", None)),
        (lambda: api_error(openai.APIStatusError, 418), ("permanent", None)),
    ],
)
def test_api_errors_are_classified(make_error, expected):
    provider, _ = provider_for(make_error())
    kind, retry_after = expected
    if kind == "transient":
        with pytest.raises(TransientProviderError) as caught:
            provider.translate(REQUEST)
        assert caught.value.retry_after == retry_after
    else:
        with pytest.raises(PermanentProviderError) as caught:
            provider.translate(REQUEST)
        assert caught.value.fatal is (kind == "fatal")


def test_helpful_messages_for_quota_and_model_problems():
    provider, _ = provider_for(api_error(openai.RateLimitError, 429, body={"code": "insufficient_quota"}))
    with pytest.raises(PermanentProviderError, match="no credit left"):
        provider.translate(REQUEST)
    provider, _ = provider_for(api_error(openai.NotFoundError, 404))
    with pytest.raises(PermanentProviderError, match="gpt-5.4-mini.*TRANSLATION_MODEL"):
        provider.translate(REQUEST)


def test_provider_status_for_openai(settings, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = dataclasses.replace(settings, translation_provider="openai", translation_api_key="")
    status = provider_status(config)
    assert not status.ready and "TRANSLATION_API_KEY" in status.message and status.label == "OpenAI (gpt-5.4-mini)"
    with pytest.raises(ProviderSetupError):
        get_provider(config)

    keyed = dataclasses.replace(config, translation_api_key="sk-test")
    assert provider_status(keyed).ready and not provider_status(keyed).is_test
    assert isinstance(get_provider(keyed), OpenAIProvider)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert provider_status(config).ready  # the standard environment variable works too


def test_model_defaults_follow_the_provider_and_can_be_overridden(settings):
    assert resolved_model(dataclasses.replace(settings, translation_provider="openai")) == "gpt-5.4-mini"
    assert resolved_model(dataclasses.replace(settings, translation_provider="claude")) == "claude-opus-5-5"
    custom = dataclasses.replace(settings, translation_provider="openai", translation_model="my-model")
    assert resolved_model(custom) == "my-model"
    assert provider_status(dataclasses.replace(custom, translation_api_key="k")).model == "my-model"
