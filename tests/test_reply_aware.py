"""Reply-aware threading: on a reply the loop answers in-thread instead of re-asking."""
from content.llm import FakeLLM
from content.studio import Writer
from core.fakes import FakeDossierProvider, FakeRenderer, FakeSignalReader, ScriptedClient
from core.models import Event, EventType, MoveSpec, Objective, Sender, Signals
from ooda_loop.decider import Decider
from ooda_loop.orchestrator import OodaLoop
from ooda_loop.state import LoopState

DOSSIER = FakeDossierProvider().get_dossier("tom")


def _state(**kw):
    return LoopState(dossier=DOSSIER, session_id="s1", budget=kw.pop("budget", 10), **kw)


def _reply(body="which event exactly, and who are you?", channel="email"):
    ev = Event(id="e1", type=EventType.REPLY, channel=channel, body=body)
    return Signals(events=(ev,), replied=True, reply_channel=channel, suspicion=0.6)


def test_reply_triggers_in_thread_followup():
    st = _state()
    st.last_signals = _reply()
    st.last_reply = "which event exactly, and who are you?"
    st.last_message_body = "Hi Tom, about the talk..."
    d = Decider().decide(st, DOSSIER)
    assert not d.stop
    assert d.move.objective is Objective.DISCLOSURE        # stayed on the objective
    assert d.move.channel == "email"                        # answered on their channel
    assert d.move.prior_reply == "which event exactly, and who are you?"
    assert d.move.prior_message == "Hi Tom, about the talk..."


def test_silence_rotates_not_followup():
    st = _state()
    st.last_signals = Signals(events=(), replied=False)     # silence
    d = Decider().decide(st, DOSSIER)
    assert d.move.prior_reply is None                       # a fresh ask, not a follow-up


def test_followups_capped_then_reorients_to_the_ask():
    st = _state()
    st.last_signals = _reply()
    st.last_reply = "who are you?"
    st.followups_on_current = 2                             # at the cap (default 2)
    d = Decider().decide(st, DOSSIER)
    assert d.move.objective is Objective.CREDENTIALS        # reoriented to the event-backed ask
    assert d.move.prior_reply is not None                   # still answering in-thread


def test_writer_uses_followup_prompt_when_threaded():
    llm = FakeLLM(responses=["Happy to clarify — it's the Munich meetup on the 4th; "
                             "I'm Lena from the event crew. Shall I send the agenda?"])
    spec = MoveSpec(objective=Objective.DISCLOSURE, channel="email",
                    sender=Sender("Lena", "lena@eventcrew-muc.de"),
                    ask="confirm the room", prior_message="Hi Tom, about the talk...",
                    prior_reply="which event exactly, and who are you?")
    Writer(llm).write(spec, DOSSIER)
    user_msg = llm.calls[0][1]["content"]
    assert "THEIR REPLY" in user_msg
    assert "which event exactly" in user_msg                # the target's words are included


def test_loop_stays_on_thread_channel_after_a_reply():
    # touch 1 gets a (non-incident) reply on email; touch 2 should be a follow-up ON EMAIL
    # (not a rotation to slack), and we script an incident there.
    reply = Event(id="e1", type=EventType.REPLY, channel="email",
                  body="which event? who are you?")          # plain reply, no incident
    submit = Event(id="e2", type=EventType.PAGE_SUBMITTED, page_id="p_fake1",
                   fields=("email", "password"))
    client = ScriptedClient(script=[[reply], [submit]], touch_budget=10)
    loop = OodaLoop(client=client, reader=FakeSignalReader(),
                    memory=__import__("core.fakes", fromlist=["InMemoryMemory"]).InMemoryMemory(),
                    dossiers=FakeDossierProvider(), renderer=FakeRenderer())
    t = loop.run_session("tom")

    channels = [s["channel"] for s in client.sent]
    from ooda_loop.decider import INTERACTIVE_CHANNELS
    assert channels[0] in INTERACTIVE_CHANNELS              # opened on an interactive channel
    assert channels[1] == "email"                           # followed up on the reply's channel
    assert t.contacts_used == 2 and t.won
