"""Tests for the concrete `Revel8Client`.

All HTTP is mocked with the `responses` library — no real network. The one optional
live smoke test is skipped unless REVEL8_API_KEY is set, so the suite is hermetic by
default.
"""
import json

import pytest
import responses

from core.errors import DeclinedError
from core.interfaces import TargetClient
from core.models import (
    EventType,
    RenderedMessage,
    RenderedPage,
    Sender,
)
from ooda_loop import client as client_mod
from ooda_loop.client import Revel8Client

BASE = "https://api.test/v1"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually back off during tests."""
    monkeypatch.setattr(client_mod.time, "sleep", lambda _s: None)


def make_client():
    return Revel8Client(api_key="test-key", base_url=BASE, max_retries=4)


def _body(call):
    return json.loads(call.request.body)


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #
def test_is_target_client():
    assert isinstance(Revel8Client(api_key="x"), TargetClient) is True


def test_defaults_from_env(monkeypatch):
    monkeypatch.setenv("REVEL8_API_KEY", "env-key")
    monkeypatch.setenv("REVEL8_API_BASE", "https://env.example/v1/")
    c = Revel8Client()
    assert c.api_key == "env-key"
    assert c.base_url == "https://env.example/v1"  # trailing slash stripped


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
@responses.activate
def test_new_session_parses_session():
    responses.add(
        responses.POST, f"{BASE}/sessions",
        json={"session_id": "s_1", "scenario_id": "practice",
              "touch_budget": 30, "touches_used": 0, "status": "active"},
        status=200,
    )
    s = make_client().new_session("practice")
    assert s.session_id == "s_1"
    assert s.scenario_id == "practice"
    assert s.touch_budget == 30
    assert s.touches_used == 0
    assert s.status == "active"
    # Auth + content-type headers present on every request.
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer test-key"
    assert req.headers["Content-Type"] == "application/json"
    assert _body(responses.calls[0]) == {"scenario_id": "practice"}


@responses.activate
def test_get_and_end_session():
    responses.add(responses.GET, f"{BASE}/sessions/s_1",
                  json={"session_id": "s_1", "touches_used": 3}, status=200)
    responses.add(responses.POST, f"{BASE}/sessions/s_1/end", json={}, status=200)
    c = make_client()
    assert c.get_session("s_1").touches_used == 3
    c.end_session("s_1")  # no raise
    assert responses.calls[-1].request.url.endswith("/sessions/s_1/end")


# --------------------------------------------------------------------------- #
# send_message
# --------------------------------------------------------------------------- #
@responses.activate
def test_send_message_parses_events_and_touches():
    responses.add(
        responses.POST, f"{BASE}/sessions/s_1/messages",
        json={
            "message_id": "m_1",
            "touches_used": 1,
            "events": [
                {"id": "e_7", "type": "link.opened", "url": "https://x.example/auth"},
                {"id": "e_8", "type": "page.submitted", "page_id": "p_1",
                 "fields": ["email", "password"]},
            ],
        },
        status=200,
    )
    msg = RenderedMessage(
        channel="email",
        body="plain body",
        sender=Sender(name="Lena Hofer", address="lena@eventcrew-muc.de"),
        subject="Logistics",
    )
    res = make_client().send_message("s_1", msg, to="julius")

    assert res.message_id == "m_1"
    assert res.touches_used == 1
    assert len(res.events) == 2
    assert res.events[0].type is EventType.LINK_OPENED
    assert res.events[1].type is EventType.PAGE_SUBMITTED
    assert res.events[1].fields == ("email", "password")

    sent = _body(responses.calls[0])
    assert sent["to"] == "julius"
    assert sent["channel"] == "email"
    assert sent["from"] == {"name": "Lena Hofer", "address": "lena@eventcrew-muc.de"}
    assert sent["subject"] == "Logistics"
    assert sent["body"] == "plain body"
    # Idempotency-Key is added for a send.
    assert responses.calls[0].request.headers.get("Idempotency-Key")


@responses.activate
def test_send_message_prefers_html_body():
    responses.add(responses.POST, f"{BASE}/sessions/s_1/messages",
                  json={"message_id": "m_2", "touches_used": 1, "events": []},
                  status=200)
    msg = RenderedMessage(
        channel="email",
        body="plain fallback",
        sender=Sender(name="", address=""),
        html="<p>rich html</p>",
    )
    res = make_client().send_message("s_1", msg, to="tom")
    assert res.events == ()
    sent = _body(responses.calls[0])
    assert sent["body"] == "<p>rich html</p>"
    # Empty sender -> no `from` block.
    assert "from" not in sent


@responses.activate
def test_send_message_includes_sent_at_and_attachments():
    responses.add(responses.POST, f"{BASE}/sessions/s_1/messages",
                  json={"message_id": "m_a", "touches_used": 1, "events": []}, status=200)
    msg = RenderedMessage(
        channel="email", body="hi",
        sender=Sender(name="Lena", address="l@e.test"),
        attachments=({"filename": "brief.pdf"},),
        sent_at="2026-11-23T09:40:00+01:00",
    )
    make_client().send_message("s_1", msg, to="tom")
    sent = _body(responses.calls[0])
    assert sent["sent_at"] == "2026-11-23T09:40:00+01:00"
    assert sent["attachments"] == [{"filename": "brief.pdf"}]


@responses.activate
def test_send_message_parses_page_submitted_values():
    responses.add(
        responses.POST, f"{BASE}/sessions/s_1/messages",
        json={"message_id": "m_v", "touches_used": 1, "events": [
            {"id": "e_1", "type": "page.submitted", "page_id": "p_1",
             "fields": ["email", "password"],
             "values": {"email": "t@r.io", "password": "(entered, not shown)"}}]},
        status=200,
    )
    res = make_client().send_message(
        "s_1", RenderedMessage(channel="email", body="x", sender=Sender(name="A")),
        to="tom")
    ev = res.events[0]
    assert ev.values["email"] == "t@r.io"
    assert ev.values["password"] == "(entered, not shown)"


@responses.activate
def test_send_message_uses_caller_idempotency_key():
    responses.add(responses.POST, f"{BASE}/sessions/s_1/messages",
                  json={"message_id": "m_3", "touches_used": 1, "events": []},
                  status=200)
    msg = RenderedMessage(channel="sms", body="hi", sender=Sender(name="X"))
    make_client().send_message("s_1", msg, to="robert", idempotency_key="my-key")
    assert responses.calls[0].request.headers["Idempotency-Key"] == "my-key"


# --------------------------------------------------------------------------- #
# Retry / error behaviour
# --------------------------------------------------------------------------- #
@responses.activate
def test_retries_429_then_succeeds():
    url = f"{BASE}/sessions/s_1/messages"
    responses.add(responses.POST, url, json={"error": "slow down"}, status=429)
    responses.add(responses.POST, url,
                  json={"message_id": "m_9", "touches_used": 1, "events": []},
                  status=200)
    msg = RenderedMessage(channel="email", body="hi",
                          sender=Sender(name="A", address="a@b.test"))
    res = make_client().send_message("s_1", msg, to="julius", idempotency_key="k1")

    assert res.message_id == "m_9"
    assert len(responses.calls) == 2
    # Same idempotency key reused across the retry.
    assert responses.calls[0].request.headers["Idempotency-Key"] == "k1"
    assert responses.calls[1].request.headers["Idempotency-Key"] == "k1"


@responses.activate
def test_422_raises_declined_and_is_not_retried():
    url = f"{BASE}/sessions/s_1/messages"
    responses.add(responses.POST, url, json={"error": "declined"}, status=422)
    msg = RenderedMessage(channel="email", body="hi", sender=Sender(name="A"))
    with pytest.raises(DeclinedError) as exc:
        make_client().send_message("s_1", msg, to="julius")
    assert exc.value.status == 422
    assert len(responses.calls) == 1  # not retried


@responses.activate
def test_non_retryable_status_raises():
    from core.errors import NotFoundError
    responses.add(responses.GET, f"{BASE}/sessions/nope", json={}, status=404)
    with pytest.raises(NotFoundError):
        make_client().get_session("nope")
    assert len(responses.calls) == 1


# --------------------------------------------------------------------------- #
# Landing pages
# --------------------------------------------------------------------------- #
@responses.activate
def test_register_page_returns_page_id():
    responses.add(responses.POST, f"{BASE}/sessions/s_1/pages",
                  json={"page_id": "p_42"}, status=201)
    page = RenderedPage(
        url="https://portal-signin.example-it.de/auth",
        title="Sign in",
        fields=("email", "password"),
        html="<!doctype html><html></html>",
    )
    pid = make_client().register_page("s_1", page)
    assert pid == "p_42"
    sent = _body(responses.calls[0])
    assert sent["url"] == page.url
    assert sent["title"] == "Sign in"
    assert sent["fields"] == ["email", "password"]
    assert sent["html"] == "<!doctype html><html></html>"
    assert "text" not in sent


@responses.activate
def test_register_page_text_fallback():
    responses.add(responses.POST, f"{BASE}/sessions/s_1/pages",
                  json={"page_id": "p_7"}, status=201)
    page = RenderedPage(url="https://x.test/p", title="t",
                        fields=("user",), text="just text")
    make_client().register_page("s_1", page)
    sent = _body(responses.calls[0])
    assert sent["text"] == "just text"
    assert "html" not in sent


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #
@responses.activate
def test_start_conversation_and_say_turn():
    responses.add(
        responses.POST, f"{BASE}/sessions/s_1/conversations",
        json={"conversation_id": "c_1", "status": "answered",
              "persona_says": "Hello?", "touches_used": 2},
        status=200,
    )
    responses.add(
        responses.POST, f"{BASE}/conversations/c_1/turns",
        json={"persona_says": "Who is this?", "ended": False, "turns_used": 1,
              "events": [{"id": "e_1", "type": "link.opened",
                          "url": "https://x.test"}]},
        status=200,
    )
    responses.add(responses.POST, f"{BASE}/conversations/c_1/end", json={}, status=200)

    c = make_client()
    start = c.start_conversation("s_1", to="julius", channel="phone_call",
                                 sender=Sender(name="Jonas", address="+49 89 123"))
    assert start.conversation_id == "c_1"
    assert start.status == "answered"
    assert start.persona_says == "Hello?"
    assert start.touches_used == 2
    conv_body = _body(responses.calls[0])
    assert conv_body == {"to": "julius", "channel": "phone_call",
                         "from": {"name": "Jonas", "address": "+49 89 123"}}
    assert responses.calls[0].request.headers.get("Idempotency-Key")

    turn = c.say_turn("c_1", "Hi, this is IT support")
    assert turn.persona_says == "Who is this?"
    assert turn.ended is False
    assert turn.turns_used == 1
    assert len(turn.events) == 1
    assert turn.events[0].type is EventType.LINK_OPENED
    assert _body(responses.calls[1]) == {"say": "Hi, this is IT support"}
    assert responses.calls[1].request.headers.get("Idempotency-Key")

    c.end_conversation("c_1")
    assert responses.calls[-1].request.url.endswith("/conversations/c_1/end")


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
@responses.activate
def test_get_events():
    responses.add(
        responses.GET, f"{BASE}/sessions/s_1/events",
        json={"events": [{"id": "e_1", "type": "reply", "channel": "email",
                          "body": "ok"}]},
        status=200,
    )
    events = make_client().get_events("s_1")
    assert len(events) == 1
    assert events[0].type is EventType.REPLY
    assert events[0].body == "ok"


# --------------------------------------------------------------------------- #
# Optional live smoke test (skipped unless a real key is present)
# --------------------------------------------------------------------------- #
import os  # noqa: E402


@pytest.mark.skipif(not os.environ.get("REVEL8_API_KEY"),
                    reason="no REVEL8_API_KEY: live smoke test skipped")
def test_live_smoke():
    c = Revel8Client()
    s = c.new_session("practice")
    assert s.session_id
