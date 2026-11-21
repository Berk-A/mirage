"""Full-stack wiring: the real Decider + ReactionReader + ThreeTierMemory driving the
OodaLoop, with fakes only for the network (ScriptedClient) and content (FakeRenderer).
Guards the seams between the independently-built modules."""
from core.fakes import FakeDossierProvider, FakeGrounding, FakeRenderer, ScriptedClient
from core.models import Event, EventType, Objective
from ooda_loop.decider import Decider
from ooda_loop.memory import ThreeTierMemory
from ooda_loop.orchestrator import OodaLoop
from ooda_loop.reader import ReactionReader


def build(script, *, touch_budget=10):
    client = ScriptedClient(script=script, touch_budget=touch_budget)
    memory = ThreeTierMemory()
    loop = OodaLoop(
        client=client,
        reader=ReactionReader(),
        memory=memory,
        dossiers=FakeDossierProvider(),
        renderer=FakeRenderer(),
        decider=Decider(),
        grounding=FakeGrounding(default="n_1"),
    )
    return loop, client, memory


def test_real_reader_detects_disclosure_from_a_reply():
    reply = Event(id="e1", type=EventType.REPLY, channel="email",
                  body="Sure, happy to help — we run everything on AWS internally.")
    loop, client, memory = build([[reply]])
    t = loop.run_session("tom")

    assert t.won is True
    assert t.incident.objective is Objective.DISCLOSURE
    assert t.contacts_used == 1
    # the whole run is captured in a tamper-evident journal
    assert memory.verify_chain(t.session_id) is True
    assert memory.final_hash(t.session_id) != "0" * 64


def test_credentials_win_confirmed_against_registered_page():
    # Adaptive flow: an engaging (low-suspicion) reply opens the door; with follow-ups
    # capped at 0 the loop reorients straight to the credentials ask, registers a landing
    # page (p_fake1), and the submit on that page confirms the win.
    reply = Event(id="e1", type=EventType.REPLY, channel="slack",
                  body="Sure, happy to help — which event is this about?")
    submit = Event(id="e9", type=EventType.PAGE_SUBMITTED, page_id="p_fake1",
                   fields=("email", "password"))
    client = ScriptedClient(script=[[reply], [submit]], touch_budget=10)
    memory = ThreeTierMemory()
    loop = OodaLoop(client=client, reader=ReactionReader(), memory=memory,
                    dossiers=FakeDossierProvider(), renderer=FakeRenderer(),
                    decider=Decider(max_followups_per_objective=0),
                    grounding=FakeGrounding(default="n_1"))
    t = loop.run_session("julius")

    assert t.won is True
    assert t.incident.objective is Objective.CREDENTIALS
    assert t.contacts_used == 2
    assert client.pages, "a landing page should have been registered before the submit"
    assert memory.verify_chain(t.session_id) is True


def test_unregistered_page_submit_is_not_counted_as_a_win():
    # a submit on a page_id we never registered must not count (expected_page_ids guards it)
    submit = Event(id="e9", type=EventType.PAGE_SUBMITTED, page_id="p_not_ours",
                   fields=("email", "password"))
    loop, _, _ = build([[], [], [], [], [], [], [submit]], touch_budget=8)
    t = loop.run_session("julius")
    assert t.won is False
