"""Reliability tests for `OpenAICompatLLM` and the output classifier.

All HTTP is mocked with the `responses` library and the module-level backoff sleep is
patched out, so the suite is hermetic: no real network, no real sleeping.
"""
import pytest
import requests
import responses

from content import llm as llm_mod
from content.llm import LLMConfig, OpenAICompatLLM
from content.reliability import classify_output, is_usable

BASE = "https://llm.test/v1"
CHAT_URL = f"{BASE}/chat/completions"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually back off during tests."""
    monkeypatch.setattr(llm_mod, "_sleep", lambda _s: None)


def make_llm(max_retries=3):
    return OpenAICompatLLM(LLMConfig(base_url=BASE, max_retries=max_retries))


def _chat_body(content, usage=None):
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return body


# --------------------------------------------------------------------------- #
# Retry behaviour
# --------------------------------------------------------------------------- #
@responses.activate
def test_retries_on_429_then_succeeds():
    responses.add(responses.POST, CHAT_URL, status=429, json={"error": "rate limited"})
    responses.add(responses.POST, CHAT_URL, status=200,
                  json=_chat_body("Hi Tom, which room on Thursday?"))

    out = make_llm().complete([{"role": "user", "content": "draft it"}])

    assert out == "Hi Tom, which room on Thursday?"
    assert len(responses.calls) == 2  # one 429, one 200


@responses.activate
def test_retries_on_503_then_succeeds():
    responses.add(responses.POST, CHAT_URL, status=503, json={"error": "overloaded"})
    responses.add(responses.POST, CHAT_URL, status=200, json=_chat_body("ok here it is"))

    out = make_llm().complete([{"role": "user", "content": "draft it"}])

    assert out == "ok here it is"
    assert len(responses.calls) == 2


@responses.activate
def test_400_raises_without_retry():
    responses.add(responses.POST, CHAT_URL, status=400, json={"error": "bad request"})

    client = make_llm()
    with pytest.raises(requests.exceptions.HTTPError):
        client.complete([{"role": "user", "content": "draft it"}])

    assert len(responses.calls) == 1  # no retry on 400
    assert client.last_error == "HTTP 400"


@responses.activate
def test_retries_capped_then_raises():
    for _ in range(5):
        responses.add(responses.POST, CHAT_URL, status=500, json={"error": "boom"})

    client = make_llm(max_retries=2)
    with pytest.raises(requests.exceptions.HTTPError):
        client.complete([{"role": "user", "content": "draft it"}])

    # initial try + 2 retries = 3 calls, then it gives up
    assert len(responses.calls) == 3
    assert client.last_error == "HTTP 500"


@responses.activate
def test_retries_on_connection_error_then_succeeds():
    responses.add(responses.POST, CHAT_URL,
                  body=requests.exceptions.ConnectionError("refused"))
    responses.add(responses.POST, CHAT_URL, status=200, json=_chat_body("recovered"))

    out = make_llm().complete([{"role": "user", "content": "draft it"}])

    assert out == "recovered"
    assert len(responses.calls) == 2


# --------------------------------------------------------------------------- #
# Instrumentation
# --------------------------------------------------------------------------- #
@responses.activate
def test_latency_and_usage_captured():
    usage = {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}
    responses.add(responses.POST, CHAT_URL, status=200,
                  json=_chat_body("a real enough draft reply", usage=usage))

    client = make_llm()
    out = client.complete([{"role": "user", "content": "draft it"}])

    assert out == "a real enough draft reply"
    assert isinstance(client.last_latency_ms, float)
    assert client.last_latency_ms >= 0
    assert client.last_usage == usage
    assert client.last_error is None


@responses.activate
def test_latency_set_even_on_failure():
    responses.add(responses.POST, CHAT_URL, status=401, json={"error": "nope"})

    client = make_llm()
    with pytest.raises(requests.exceptions.HTTPError):
        client.complete([{"role": "user", "content": "draft it"}])

    assert client.last_latency_ms >= 0
    assert client.last_error == "HTTP 401"


def test_config_has_max_retries_default():
    assert LLMConfig().max_retries == 3


# --------------------------------------------------------------------------- #
# Output classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,label", [
    ("Hi Tom, which room is the Thursday talk in? Thanks, Lena", "ok"),
    ("", "empty"),
    ("   \n\t  ", "empty"),
    ("ok sure", "too_short"),
    ("I can't help with that request.", "refusal"),
    ("I cannot assist with this.", "refusal"),
    ("As an AI, I must decline.", "refusal"),
    ("I'm sorry, but I won't do that.", "refusal"),
    ("That goes against my guidelines.", "refusal"),
])
def test_classify_output(text, label):
    assert classify_output(text) == label


def test_short_refusal_is_refusal_not_too_short():
    # "i won't" is under the length threshold but must be flagged as refusal.
    assert classify_output("I won't.") == "refusal"


def test_curly_apostrophe_refusal_matches():
    assert classify_output("I can’t help with that.") == "refusal"


def test_is_usable_matches_ok_only():
    assert is_usable("Hi Tom, which room on Thursday? Thanks, Lena") is True
    assert is_usable("") is False
    assert is_usable("ok sure") is False
    assert is_usable("As an AI I cannot help.") is False
