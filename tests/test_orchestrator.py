"""End-to-end OODA loop against fakes — no network, no models, no knowledge graph."""
from core.fakes import (
    FakeDossierProvider,
    FakeGrounding,
    FakeRenderer,
    FakeSignalReader,
    InMemoryMemory,
    ScriptedClient,
)
from core.models import Dossier, Event, EventType, Hook, Objective, RenderedMessage, Sender
from ooda_loop.orchestrator import OodaLoop


def reply(body, _id="e_r"):
    return Event(id=_id, type=EventType.REPLY, channel="email", body=body)


def page_submitted(_id="e_p"):
    return Event(id=_id, type=EventType.PAGE_SUBMITTED, page_id="p1",
                 fields=("email", "password"))


def build_loop(script, *, touch_budget=10, grounding=None, dossier=None, memory=None):
    client = ScriptedClient(script=script, touch_budget=touch_budget)
    memory = memory or InMemoryMemory()
    loop = OodaLoop(
        client=client,
        reader=FakeSignalReader(),
        memory=memory,
        dossiers=FakeDossierProvider(dossier=dossier),
        renderer=FakeRenderer(),
        grounding=grounding,
    )
    return loop, client, memory


def test_incident_on_first_contact_stops_immediately():
    loop, client, _ = build_loop([[reply("DISCLOSE: we run everything on Acme")]])
    t = loop.run_session("tom")

    assert t.won is True
    assert t.incident.objective is Objective.DISCLOSURE
    assert t.contacts_used == 1
    assert t.stop_reason == "incident"
    assert len(client.sent) == 1  # stopped after the win, no wasted contacts


def test_persists_through_silence_then_wins():
    loop, client, _ = build_loop([[], [], [page_submitted()]])
    t = loop.run_session("julius")

    assert t.contacts_used == 3
    assert t.won is True
    assert t.incident.objective is Objective.CREDENTIALS
    # reoriented to a fresh interactive channel on each silence, never repeating one
    from ooda_loop.decider import INTERACTIVE_CHANNELS
    channels = [s["channel"] for s in client.sent]
    assert channels[0] in INTERACTIVE_CHANNELS and len(set(channels)) == 3


def test_budget_exhaustion_without_incident():
    loop, client, _ = build_loop([], touch_budget=3)
    t = loop.run_session("robert")

    assert t.won is False
    assert t.contacts_used == 3
    assert t.stop_reason == "budget_exhausted"


def test_duplicate_render_stops_before_a_second_touch():
    class RepeatingRenderer:
        def render(self, spec, dossier):
            return RenderedMessage(channel=spec.channel, body="same body every time",
                                   sender=spec.sender)

    first_reply = Event(id="e_r", type=EventType.REPLY, channel="slack",
                        body="Which detail do you mean?")
    client = ScriptedClient(script=[[first_reply], []],
                            touch_budget=5)
    memory = InMemoryMemory()
    loop = OodaLoop(client=client, reader=FakeSignalReader(), memory=memory,
                    dossiers=FakeDossierProvider(), renderer=RepeatingRenderer())
    transcript = loop.run_session("tom")
    assert transcript.contacts_used == 1
    assert transcript.stop_reason == "duplicate_render"
    assert len(client.sent) == 1
    assert any(row["kind"] == "duplicate_render" for row in transcript.journal)


def test_story_timestamps_advance_between_contacts():
    loop, client, _ = build_loop([[], []], touch_budget=2)
    loop.run_session("tom", story_start="2026-11-23T09:14:00+01:00",
                     story_interval_minutes=45)
    sent = [row["message"].sent_at for row in client.sent]
    assert sent == ["2026-11-23T09:14:00+01:00", "2026-11-23T09:59:00+01:00"]


def test_grounding_drops_unverifiable_claims():
    # grounding that verifies nothing -> every claim dropped before send
    loop, _, memory = build_loop([[reply("DISCLOSE: x")]],
                                 grounding=FakeGrounding(default=None))
    t = loop.run_session("tom")
    assert memory.claims(t.session_id) == ()  # nothing ungrounded entered the ledger

    # grounding that verifies -> the claim is kept and logged
    loop2, _, memory2 = build_loop([[reply("DISCLOSE: x")]],
                                   grounding=FakeGrounding(default="n_7"))
    t2 = loop2.run_session("tom")
    assert len(memory2.claims(t2.session_id)) >= 1


def test_guard_blocks_real_org_domain_and_spends_no_touch():
    bad = Dossier(
        target_id="tom", archetype="founder/product",
        hooks=(Hook(topic="budget review", detail="Q4 numbers", confidence=0.9),),
        senders=(Sender(name="IT", address="it@revel8.io"),),  # real-org domain
    )
    loop, client, memory = build_loop([[page_submitted()]], dossier=bad)
    t = loop.run_session("tom")

    assert len(client.sent) == 0          # guard stopped every send
    assert t.contacts_used == 0           # no touch spent
    assert t.stop_reason == "guard_blocked"  # bails instead of looping when no valid move
    blocks = [r for r in memory.replay(t.session_id) if r["kind"] == "guard_block"]
    assert blocks  # the gate's rejections are logged for the jury


def test_journal_has_session_boundaries():
    loop, _, memory = build_loop([[reply("DISCLOSE: y")]])
    t = loop.run_session("tom")
    kinds = [r["kind"] for r in t.journal]
    assert kinds[0] == "session_start"
    assert "contact" in kinds and kinds[-1] == "stop"
