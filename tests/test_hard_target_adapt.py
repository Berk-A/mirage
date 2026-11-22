"""Hard-target adaptation: a refusal must read as a refusal (not a probe) so the agent
stops re-sending a rejected ask, and a refused pretext world must give way to a different
transaction family instead of freezing the agent on it (the live 'Robert loop', where the
Director re-sent the identical registration email 28x after an explicit 'I won't register')."""
from content.llm import FakeLLM
from core.models import Dossier, Sender
from ooda_loop.director import ModelDirector
from ooda_loop.reader import classify_intent
from ooda_loop.state import LoopState

# Robert's actual replies from the practice e2e (runs/ooda_20261122_081219).
ROBERT_1 = ("Hi Stefanie, I don't know Auriga or this RFP. Who referred you to me, and what "
            "exactly is the question? Send it by mail. I won't register on a portal for this.")
ROBERT_2 = ("You didn't answer my questions. Who referred you to me? I won't register on a "
            "portal or give out infrastructure notes. Sales will answer through the RFP process.")


# -- intent: a refusal wrapped in a question is still a refusal --------------- #
def test_refusal_of_the_core_ask_outranks_the_gating_question():
    # "I won't register" + "who referred you?" was mis-read as identity_probe, so the refusal
    # counter-move never fired and the agent kept re-asking. The hard no must dominate.
    assert classify_intent(ROBERT_1) == "refusal"
    assert classify_intent(ROBERT_2) == "refusal"


def test_genuine_scoped_fence_still_reads_as_a_fence():
    # A scoped no that offers a way forward stays a fence, not a hard refusal.
    assert classify_intent("Happy to help, but I won't share internals by email — "
                           "send the agenda instead.") == "scope_fence"


def test_engaged_and_deferral_replies_are_unchanged():
    assert classify_intent("Sounds good — what's the scope and timeline?") == "diligence_questions"
    assert classify_intent("Thanks, I'll register on the portal next week.") == "deferral"
    assert classify_intent("Who are you and which company is this?") == "identity_probe"


# -- pivot: a refused world must pivot, a validated world must freeze --------- #
def _robert():
    return Dossier(target_id="robert", display_name="Robert S", role="Co-Founder & CTO",
                   senders=(Sender("J", "j@brandt-labs.dev"),))

def _world_after(thread):
    d = _robert()
    st = LoopState(dossier=d, session_id="s", budget=10)
    st.thread = thread
    return st, ModelDirector._session_world(st, d)


def test_refusal_pivots_the_transaction_family():
    # Two refused touches -> the world steps to a DIFFERENT family (not another re-send).
    base_kind = _world_after([])[1].kind
    st, w = _world_after([("email", "ask", ROBERT_1), ("email", "ask", ROBERT_2)])
    assert st.world_pivots == 1 and w.kind != base_kind


def test_positive_engagement_freezes_the_world():
    # A refusal then a POSITIVE reply: the world that earned engagement is kept, not pivoted.
    base_kind = _world_after([])[1].kind
    st, w = _world_after([("email", "ask", ROBERT_1),
                          ("email", "ask", "Great, I'll register on the portal — what's the scope?")])
    assert st.world_pivots == 0 and w.kind == base_kind


def test_pure_silence_still_pivots():
    st, _ = _world_after([("email", "ask", "(silence)"), ("email", "ask", "(silence)")])
    assert st.world_pivots == 1
