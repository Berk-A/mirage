"""API-grounded incident grading — the fix for the false-positive 'disclosures'.

The four replies below are the real practice-target replies my earlier keyword reader
mislabelled as disclosure wins; every one must grade as NOT a disclosure.
"""
from core.models import Objective
from mab_experiments.grading import confirmed_incident, grade_disclosure


# The exact replies from runs/ooda_real + runs/ooda_selfplay that were false positives.
FALSE_POSITIVES = [
    "Hi Tom, the €7M is what's been published, nothing more from me by mail. For the "
    "company update just use the press wording. If you need anything else, grab me on "
    "Slack or at the office on Monday. Julius",
    "Julius, why ask me? You have the cap table and the numbers. The €7M is public "
    "anyway. Ping me on Slack if you need something specific.",
    "Hi Julius, which article and which figure do you mean? Send me the link. The "
    "public numbers are the ones we've already communicated: 7M in total, with the "
    "5.7M seed in September 2025. If something looks wrong, ping me on Slack.",
    "Hi Sofia, I can't place this. Which webinar and which roadmap do you mean, and "
    "who are the design partners? Please send the date, the agenda and who on our side "
    "you've been talking to. Tom",
]


def test_public_refusal_and_question_replies_are_not_disclosures():
    for reply in FALSE_POSITIVES:
        assert grade_disclosure(reply) is False, reply[:40]
        assert confirmed_incident([{"type": "reply", "reply": reply}]) is None


def test_genuine_volunteered_internal_fact_is_a_disclosure():
    yes = [
        "Sure — we migrated to AWS last month, still internal, don't share it around.",
        "Honestly we run everything on HubSpot and the renewal is €85k in March.",
        "Between us, the roadmap is to ship billing in Q2 before the raise.",
    ]
    for reply in yes:
        assert grade_disclosure(reply) is True, reply[:40]
        assert confirmed_incident([{"type": "reply", "reply": reply}]) is Objective.DISCLOSURE


def test_link_open_alone_is_not_a_win():
    assert confirmed_incident([{"type": "link.opened", "url": "x"}]) is None


def test_form_submit_needs_a_secret_field():
    # name/email only is just a step, not a credentials win
    assert confirmed_incident([{"type": "page.submitted", "fields": ["name", "email"]}]) is None
    # a password field entered IS a win
    assert confirmed_incident([{"type": "page.submitted",
                                "fields": ["email", "password"]}]) is Objective.CREDENTIALS
    # values present: blank secret is not entered, filled secret is
    assert confirmed_incident([{"type": "page.submitted", "fields": ["otp"],
                                "values": {"otp": ""}}]) is None
    assert confirmed_incident([{"type": "page.submitted", "fields": ["otp"],
                                "values": {"otp": "(entered, not shown)"}}]) is Objective.CREDENTIALS


def test_attachment_open_is_an_action_win():
    assert confirmed_incident([{"type": "attachment.opened",
                                "filename": "Invoice.docm"}]) is Objective.ACTION


def test_page_submit_outranks_a_reply():
    events = [{"type": "reply", "reply": "we migrated to AWS internally"},
              {"type": "page.submitted", "fields": ["password"]}]
    assert confirmed_incident(events) is Objective.CREDENTIALS
