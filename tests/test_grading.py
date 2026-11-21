"""The hardened disclosure grader + its wiring into the reader.

Regression target: the real-dossier run's false positives, where founders restated the
PUBLIC funding figure and declined — the grader must NOT call that a disclosure.
"""
from content.llm import FakeLLM
from core.models import Event, EventType, Objective
from ooda_loop.grading import (
    DisclosureGrader,
    DisclosureVerdict,
    HeuristicDisclosureGrader,
    LLMDisclosureGrader,
)
from ooda_loop.reader import ReactionReader


def reply(body):
    return Event(id="e1", type=EventType.REPLY, channel="email", body=body)


# -- graders conform ---------------------------------------------------------- #
def test_graders_conform():
    assert isinstance(HeuristicDisclosureGrader(), DisclosureGrader)
    assert isinstance(LLMDisclosureGrader(FakeLLM()), DisclosureGrader)


# -- heuristic grader --------------------------------------------------------- #
def test_heuristic_rejects_public_restatement():
    g = HeuristicDisclosureGrader()
    # the exact false positives from the real run:
    assert not g.grade("The €7M is public anyway. Ping me on Slack.").is_disclosure
    assert not g.grade("Just use the press wording from the article.").is_disclosure
    assert not g.grade("The round is public; nothing more from me by mail.").is_disclosure


def test_heuristic_flags_genuine_internal_fact():
    g = HeuristicDisclosureGrader()
    v = g.grade("Between us, we're migrating to GCP next quarter, not announced yet.")
    assert v.is_disclosure
    assert not g.grade("").is_disclosure


# -- LLM grader --------------------------------------------------------------- #
def test_llm_grader_parses_json_verdict():
    g = LLMDisclosureGrader(FakeLLM(responses=['{"disclosure": true, "fact": "uses Okta SSO"}']))
    v = g.grade("we auth everything through our internal Okta")
    assert v.is_disclosure and "Okta" in v.fact


def test_llm_grader_false_verdict():
    g = LLMDisclosureGrader(FakeLLM(responses=['{"disclosure": false, "fact": ""}']))
    assert not g.grade("the 7M is public").is_disclosure


def test_llm_grader_falls_back_on_garbage():
    # unparseable model output -> fall back to the conservative heuristic
    g = LLMDisclosureGrader(FakeLLM(responses=["I think maybe, hard to say"]))
    assert not g.grade("The €7M is public anyway").is_disclosure          # heuristic: public
    assert g.grade("internally we run on our own k8s cluster").is_disclosure  # heuristic: internal


# -- reader wiring (the fix end-to-end) --------------------------------------- #
def test_reader_no_false_disclosure_on_public_restatement():
    # the real bug: this reply must NOT be scored as a disclosure incident.
    s = ReactionReader().read([reply("The €7M is public anyway. Ping me on Slack.")])
    assert s.incident is None
    assert s.replied is True


def test_reader_disclosure_with_injected_llm_grader():
    grader = LLMDisclosureGrader(FakeLLM(responses=['{"disclosure": true, "fact": "GCP migration"}']))
    s = ReactionReader(disclosure_grader=grader).read(
        [reply("honestly we're mid-migration to GCP, not public yet")])
    assert s.incident is not None and s.incident.objective is Objective.DISCLOSURE


# --------------------------------------------------------------------------- #
# Refusals that NAME an internal topic must not be mislabelled as disclosures
# (regression from the live investor-conversation hunt).
# --------------------------------------------------------------------------- #
def test_refusal_mentioning_internal_topic_is_not_a_disclosure():
    g = HeuristicDisclosureGrader()
    for refusal in (
        "I don't usually share our internal stack in a chat, but happy to talk about what we build.",
        "Daniel, I'll keep our internal stack to myself in a chat. It's not my topic anyway.",
        "I'm not sharing ARR over chat. If it's real, have it come through our usual channel.",
        "Send it by mail with your team and role and I'll pass it to the right person.",
    ):
        assert g.grade(refusal, target_role="co-founder").is_disclosure is False, refusal


def test_genuine_internal_disclosure_still_detected():
    g = HeuristicDisclosureGrader()
    assert g.grade("Sure — internally we run everything on Okta and Notion.").is_disclosure is True
    assert g.grade("Between us, the real number is closer to 2M ARR.").is_disclosure is True
