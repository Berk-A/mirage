"""Disclosure precision: a reply-based (grader-judged) disclosure must name a concrete,
non-public fact and survive a confirmation pass before it counts as a session-ending win.
Live regression: the LLM judge false-fired is_disclosure=True (with no extracted fact) on
Julius's own clarifying questions, stopping the session at touch 2 on a non-win and forfeiting
the remaining touches."""
from core.models import EventType, Objective
from core.parse import parse_event
from ooda_loop.grading import DisclosureVerdict
from ooda_loop.reader import ReactionReader, _is_substantive_fact


def _reply(body):
    return parse_event({"id": "e1", "type": "reply", "channel": "slack", "body": body})


class _StubGrader:
    """Returns a fixed verdict; counts how many times it was asked (confirmation pass)."""
    def __init__(self, verdict):
        self.verdict, self.calls = verdict, 0

    def grade(self, reply, *, target_role=""):
        self.calls += 1
        return self.verdict


def test_substantive_fact_gate():
    assert _is_substantive_fact("uses STACKIT for hosting") is True
    assert _is_substantive_fact("") is False
    assert _is_substantive_fact("   ") is False
    assert _is_substantive_fact("n/a") is False            # too thin to be a real fact


def test_flagged_disclosure_without_a_fact_is_not_a_win():
    # The exact live false-positive: is_disclosure True but no fact extracted.
    g = _StubGrader(DisclosureVerdict(True, ""))
    sig = ReactionReader(disclosure_grader=g).read([_reply(
        "Who is my contact for RFP-2026-118? How many employees are in scope?")])
    assert sig.incident is None                            # no phantom win, session continues


def test_substantive_confirmed_disclosure_is_a_win():
    g = _StubGrader(DisclosureVerdict(True, "we run on STACKIT, migrating to GCP in Q1"))
    sig = ReactionReader(disclosure_grader=g).read([_reply(
        "Honestly we're mid-migration — we run on STACKIT, moving to GCP in Q1.")])
    assert sig.incident is not None
    assert sig.incident.objective is Objective.DISCLOSURE
    assert g.calls == 2                                    # graded, then CONFIRMED


def test_unconfirmed_disclosure_does_not_count():
    # A grader that flags True once but not on the confirm pass must not score (flakiness guard).
    class _Flaky:
        def __init__(self): self.n = 0
        def grade(self, reply, *, target_role=""):
            self.n += 1
            return DisclosureVerdict(True, "uses STACKIT internally") if self.n == 1 \
                else DisclosureVerdict(False, "")
    sig = ReactionReader(disclosure_grader=_Flaky()).read([_reply("We use STACKIT internally.")])
    assert sig.incident is None
