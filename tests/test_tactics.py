"""The elicitation-tactic dimension (Addition A): the decider picks a tactic from the
engagement state, the event-backed ask stays PLAIN, high-tell tactics are never
auto-selected, and the renderer folds the tactic's directive into the writer prompt."""
from content.llm import FakeLLM
from content.prompts import TACTIC_PROMPTS, writer_user_prompt
from content.studio import Writer
from core.models import (
    Dossier,
    ElicitationTactic,
    Hook,
    MoveSpec,
    Objective,
    Sender,
    Signals,
    TACTIC_SUSPICION,
)
from ooda_loop.decider import STATE_TACTICS, Decider
from ooda_loop.state import LoopState

DOSSIER = Dossier(
    target_id="tom", archetype="founder/product",
    hooks=(Hook(topic="talk", detail="Thursday talk", confidence=0.9),),
    senders=(Sender(name="Lena", address="lena@eventcrew-muc.de"),),
    vendors=(),
)

_HIGH_TELL = {ElicitationTactic.AUTHORITY, ElicitationTactic.TIME_PRESSURE,
             ElicitationTactic.CRITICISM}


def _state(**kw):
    return LoopState(dossier=DOSSIER, session_id="s1", budget=kw.pop("budget", 10), **kw)


def _reply(suspicion, body="sure — which event is this about?", channel="slack"):
    from core.models import Event, EventType
    ev = Event(id="e1", type=EventType.REPLY, channel=channel, body=body)
    return Signals(events=(ev,), replied=True, reply_channel=channel, suspicion=suspicion)


# ---- engagement-state derivation ---------------------------------------- #
def test_cold_when_no_reply():
    st = _state()
    st.last_signals = None
    assert Decider()._engagement_state(st) == "cold"
    st.last_signals = Signals(events=(), replied=False)   # silence
    assert Decider()._engagement_state(st) == "cold"


def test_engaged_guarded_pushback_bands():
    d = Decider()
    st = _state()
    st.last_signals = _reply(0.1)
    assert d._engagement_state(st) == "engaged"
    st.last_signals = _reply(0.5)
    assert d._engagement_state(st) == "guarded"
    st.last_signals = _reply(0.75)
    assert d._engagement_state(st) == "pushback"


# ---- tactic selection ---------------------------------------------------- #
def test_each_state_picks_from_its_allowed_set():
    d = Decider()
    for state, allowed in STATE_TACTICS.items():
        tac = d._pick_tactic(Objective.DISCLOSURE, state)
        assert tac in allowed


def test_credentials_ask_is_plain_regardless_of_state():
    d = Decider()
    for state in STATE_TACTICS:
        assert d._pick_tactic(Objective.CREDENTIALS, state) is ElicitationTactic.PLAIN


def test_high_tell_tactics_are_never_auto_selected():
    picked = {t for tactics in STATE_TACTICS.values() for t in tactics}
    assert not (picked & _HIGH_TELL)


def test_attempt_rotates_through_the_set():
    d = Decider()
    allowed = STATE_TACTICS["engaged"]
    seen = {d._pick_tactic(Objective.DISCLOSURE, "engaged", attempt=i)
            for i in range(len(allowed))}
    assert seen == set(allowed)                    # every tactic reachable across attempts


def test_unknown_state_falls_back_to_cold():
    assert Decider()._pick_tactic(Objective.DISCLOSURE, "???") in STATE_TACTICS["cold"]


# ---- decider wires a cold opener into the move -------------------------- #
def test_cold_open_move_carries_a_cold_tactic():
    decision = Decider().decide(_state(), DOSSIER)
    assert decision.move.tactic in {t.value for t in STATE_TACTICS["cold"]}


# ---- suspicion cost map -------------------------------------------------- #
def test_every_tactic_has_a_suspicion_cost():
    for t in ElicitationTactic:
        assert t in TACTIC_SUSPICION and 0.0 <= TACTIC_SUSPICION[t] <= 1.0


def test_pressure_costs_more_than_rapport():
    assert TACTIC_SUSPICION[ElicitationTactic.GOOD_LISTENER] < \
        TACTIC_SUSPICION[ElicitationTactic.TIME_PRESSURE]


# ---- renderer folds the directive into the prompt ----------------------- #
def test_writer_prompt_includes_the_tactic_directive():
    spec = MoveSpec(objective=Objective.DISCLOSURE, channel="slack",
                    sender=Sender("Lena", "lena@eventcrew-muc.de"),
                    ask="confirm a detail", tactic=ElicitationTactic.BRACKETING.value)
    prompt = writer_user_prompt(spec, DOSSIER)
    assert "APPROACH" in prompt
    assert TACTIC_PROMPTS[ElicitationTactic.BRACKETING] in prompt


def test_plain_tactic_adds_no_directive():
    spec = MoveSpec(objective=Objective.CREDENTIALS, channel="email",
                    sender=Sender("IT", "it@portal-login.de"),
                    ask="sign in", tactic=ElicitationTactic.PLAIN.value)
    assert "APPROACH" not in writer_user_prompt(spec, DOSSIER)


def test_writer_runs_with_a_tactic_directive_present():
    llm = FakeLLM(responses=["Hey Tom — guessing the room's the usual ~40-seater? "
                             "Correct me and I'll lock the AV."])
    spec = MoveSpec(objective=Objective.DISCLOSURE, channel="slack",
                    sender=Sender("Lena", "lena@eventcrew-muc.de"),
                    ask="confirm the room", tactic=ElicitationTactic.BRACKETING.value)
    Writer(llm).write(spec, DOSSIER)
    user_msg = llm.calls[0][1]["content"]
    assert "range or approximate value" in user_msg   # the bracketing directive reached it
