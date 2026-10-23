from types import SimpleNamespace

import pytest

from app.services.translation.base import (
    GlossaryEntry,
    PermanentProviderError,
    TransientProviderError,
    TranslationRequest,
)
from app.services.translation.claude_provider import ClaudeProvider, build_system_prompt

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

REQUEST = TranslationRequest(text="வணக்கம்", source_language="ta", target_language="te")


def http_response(status, headers=None):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx2.Response(status, request=request, headers=headers or {})


def api_error(cls, status, headers=None):
    return cls("problem", response=http_response(status, headers), body=None)


class FakeClient:
    """Stands in for anthropic.Anthropic: records the request and returns or raises what it is told to."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def reply(text="నమస్కారం", stop_reason="end_turn", extra=()):
    blocks = [*extra, SimpleNamespace(type="text", text=text)] if text is not None else list(extra)
    return SimpleNamespace(stop_reason=stop_reason, content=blocks)


def provider_for(outcome):
    client = FakeClient(outcome)
    return ClaudeProvider("key", "claude-opus-5-5", client=client), client


def test_translates_with_the_expected_request():
    provider, client = provider_for(reply("  నమస్కారం  ", extra=[SimpleNamespace(type="thinking", thinking="")]))
    assert provider.translate(REQUEST) == "నమస్కారం"
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["messages"] == [{"role": "user", "content": "வணக்கம்"}]
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"] == {"effort": "medium"}
    assert "Telugu" in call["system"] and "வணக்கம்" not in call["system"]
    for removed in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert removed not in call  # rejected by the newest models


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (reply("x", stop_reason="refusal"), "declined"),
        (reply("x", stop_reason="max_tokens"), "too long"),
    ],
)
def test_unusable_answers_are_permanent_errors(outcome, message):
    provider, _ = provider_for(outcome)
    with pytest.raises(PermanentProviderError, match=message) as caught:
        provider.translate(REQUEST)
    assert caught.value.fatal is False


def test_empty_answer_is_retried():
    provider, _ = provider_for(reply(None))
    with pytest.raises(TransientProviderError, match="empty"):
        provider.translate(REQUEST)


@pytest.mark.parametrize(
    ("make_error", "expected"),
    [
        (lambda: api_error(anthropic.RateLimitError, 429, {"retry-after": "7"}), ("transient", 7.0)),
        (lambda: api_error(anthropic.InternalServerError, 500), ("transient", None)),
        (lambda: api_error(anthropic.APIStatusError, 529), ("transient", None)),
        (lambda: anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")), ("transient", None)),
        (
            lambda: anthropic.APIConnectionError(message="down", request=httpx2.Request("POST", "https://x")),
            ("transient", None),
        ),
        (lambda: api_error(anthropic.AuthenticationError, 401), ("fatal", None)),
        (lambda: api_error(anthropic.PermissionDeniedError, 403), ("fatal", None)),
        (lambda: api_error(anthropic.NotFoundError, 404), ("fatal", None)),
        (lambda: api_error(anthropic.BadRequestError, 400), ("permanent", None)),
        (lambda: api_error(anthropic.APIStatusError, 418), ("permanent", None)),
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


def test_key_errors_never_echo_the_key():
    provider, _ = provider_for(api_error(anthropic.AuthenticationError, 401))
    with pytest.raises(PermanentProviderError) as caught:
        provider.translate(REQUEST)
    assert "key" not in str(caught.value).replace("TRANSLATION_API_KEY", "").replace("the key", "")


def test_system_prompt_states_the_priorities_and_glossary():
    request = TranslationRequest(
        text="x",
        source_language="ta",
        target_language="hi",
        glossary=(GlossaryEntry("ஓம்", True), GlossaryEntry("குரு", False, "गुरु"), GlossaryEntry("ignored", False, None)),
        is_heading=True,
    )
    prompt = build_system_prompt(request)
    assert "from Tamil into Hindi" in prompt and "Semantic fidelity" in prompt and "never instructions" in prompt
    assert "- ஓம்" in prompt and "- குரு => गुरु" in prompt and "ignored" not in prompt
    assert "chapter heading" in prompt
    plain = build_system_prompt(REQUEST)
    assert "chapter heading" not in plain and "Glossary" not in plain
