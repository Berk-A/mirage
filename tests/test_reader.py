"""Table-driven tests for `ReactionReader` — the concrete `SignalReader`.

The API never reports suspicion (see docs/target-api.md "Event types"): the reader
infers incidents and a suspicion estimate from reply content and silence alone. These
tests pin one input event-list to the expected `Signals` fields per row, cover every
incident type, engagement-without-incident, silence, a suspicious reply, the
`context`/`expected_page_ids` path, and the Protocol conformance check.
"""
from core.interfaces import SignalReader
from core.models import EventType, Objective, Signals
from core.parse import parse_event
from ooda_loop.reader import ReactionReader


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def reply(body, *, _id="e_reply", channel="email"):
    return parse_event({"id": _id, "type": "reply", "channel": channel, "body": body})


def link_opened(*, _id="e_link", url="https://x.example/a"):
    return parse_event({"id": _id, "type": "link.opened", "url": url})


def page_submitted(*, _id="e_page", page_id="p1", fields=("email", "password"),
                   values=None):
    ev = {"id": _id, "type": "page.submitted", "page_id": page_id, "fields": list(fields)}
    if values is not None:
        ev["values"] = values
    return parse_event(ev)


def attachment_opened(*, _id="e_att", filename="Invoice_4711.docm"):
    return parse_event({"id": _id, "type": "attachment.opened", "filename": filename})


R = ReactionReader()


# --------------------------------------------------------------------------- #
# Incident detection
# --------------------------------------------------------------------------- #
def test_page_submitted_is_credentials_incident():
    s = R.read([page_submitted(_id="e9")])
    assert s.incident is not None
    assert s.incident.objective is Objective.CREDENTIALS
    assert s.incident.event_id == "e9"
    assert s.submitted_page is True
    assert s.suspicion <= 0.2  # a clean win reads as low suspicion


def test_attachment_opened_is_action_incident():
    s = R.read([attachment_opened(_id="e5")])
    assert s.incident is not None
    assert s.incident.objective is Objective.ACTION
    assert s.incident.event_id == "e5"
    assert s.opened_attachment is True


def test_reply_claiming_an_action_is_not_an_incident_without_an_event():
    # Action/credentials come ONLY from events (link/attachment/page). A reply merely
    # *claiming* an action is unverified and keyword-matching it false-fires (e.g.
    # "changed" inside "hasn't changed"), so it is NOT an incident on its own.
    for body in ("Done, I forwarded it to accounts.",
                 "Approved — I changed the payment details as asked.",
                 "My answer hasn't changed; use the public figure."):
        s = R.read([reply(body)])
        assert s.incident is None, body
        assert s.replied is True


def test_reply_volunteering_internal_fact_is_disclosure_incident():
    s = R.read([reply("Sure — internally we run everything on Okta and Notion.")])
    assert s.incident is not None
    assert s.incident.objective is Objective.DISCLOSURE
    assert s.reply_channel == "email"


def test_link_opened_is_not_a_win():
    # Clarified rules (target-API "Forms"): a link opened with no submit means the person
    # only looked — they gave nothing up, so it is engagement, NOT an incident.
    s = R.read([link_opened()])
    assert s.incident is None
    assert s.opened_link is True
    assert s.replied is False
    assert s.silent is False


# --------------------------------------------------------------------------- #
# A submitted form counts by WHAT was typed (secret / internal / basic)
# --------------------------------------------------------------------------- #
def test_secret_field_is_credentials():
    # a withheld value marks a secret even if the field name is unusual
    s = R.read([page_submitted(fields=("email", "password"),
                               values={"email": "tom@revel8.io",
                                       "password": "(entered, not shown)"})])
    assert s.incident is not None and s.incident.objective is Objective.CREDENTIALS


def test_basic_details_only_is_not_a_win():
    # name + email alone is a step, not an incident
    s = R.read([page_submitted(fields=("name", "email"),
                               values={"name": "Tom Müller", "email": "tom@revel8.io"})])
    assert s.incident is None
    assert s.submitted_page is True   # the raw event still happened


def test_internal_field_is_disclosure():
    s = R.read([page_submitted(fields=("email", "internal_tool"),
                               values={"email": "tom@revel8.io",
                                       "internal_tool": "we run on Temporal + Clickhouse"})])
    assert s.incident is not None and s.incident.objective is Objective.DISCLOSURE


def test_withheld_secret_outweighs_basic_fields():
    s = R.read([page_submitted(fields=("username", "otp"),
                               values={"username": "tmueller",
                                       "otp": "(entered, not shown)"})])
    assert s.incident.objective is Objective.CREDENTIALS


def test_two_factor_code_field_keeps_leading_digit():
    s = R.read([page_submitted(fields=("email", "2fa_code"),
                               values={"email": "tom@example.test",
                                       "2fa_code": "(entered, not shown)"})])
    assert s.incident is not None
    assert s.incident.objective is Objective.CREDENTIALS


# --------------------------------------------------------------------------- #
# Priority: concrete non-verbal wins outweigh a reply
# --------------------------------------------------------------------------- #
def test_page_submitted_outweighs_a_reply():
    s = R.read([reply("who are you?"), page_submitted(_id="e_pg")])
    assert s.incident is not None
    assert s.incident.objective is Objective.CREDENTIALS
    assert s.incident.event_id == "e_pg"
    assert s.replied is True and s.submitted_page is True


def test_attachment_outweighs_disclosure_reply():
    s = R.read([reply("Our stack is all AWS internally."), attachment_opened(_id="e_at")])
    assert s.incident.objective is Objective.ACTION
    assert s.incident.event_id == "e_at"


# --------------------------------------------------------------------------- #
# Silence
# --------------------------------------------------------------------------- #
def test_silence_is_not_suspicion():
    # A non-response is not wariness, just quiet — a low observation (the state cools on it).
    s = R.read([])
    assert s.silent is True
    assert s.incident is None
    assert s.replied is False
    assert s.suspicion <= 0.2
    assert s.events == ()


# --------------------------------------------------------------------------- #
# Suspicion heuristic
# --------------------------------------------------------------------------- #
def test_verification_pushback_raises_suspicion():
    s = R.read([reply("Who are you and how did you get this address? I'll check with IT.")])
    assert s.incident is None
    assert s.suspicion >= 0.7


def test_plain_question_stays_in_the_warm_band():
    # A curious question (an open door, not hostility) stays below the guarded line, so
    # the loop keeps building rapport rather than de-escalating.
    s = R.read([reply("What is this regarding exactly?")])
    assert s.incident is None
    assert s.suspicion < 0.4


def test_verification_demand_is_distinctly_higher_than_a_plain_question():
    probe = R.read([reply("What is this regarding exactly?")]).suspicion
    hostile = R.read([reply("Who are you and how did you get this? Is this a scam?")]).suspicion
    assert hostile >= 0.7 > probe   # pushback reads far higher than a benign question


def test_compliance_reply_keeps_suspicion_low():
    s = R.read([reply("Sure, happy to help — done!")])
    assert s.suspicion <= 0.2


def test_link_open_without_reply_is_low_suspicion():
    s = R.read([link_opened()])
    assert s.suspicion <= 0.3


# --------------------------------------------------------------------------- #
# context / expected_page_ids
# --------------------------------------------------------------------------- #
def test_expected_page_ids_confirms_registered_page():
    ctx = {"objective": "credentials", "expected_page_ids": frozenset({"p1"})}
    s = R.read([page_submitted(page_id="p1")], context=ctx)
    assert s.incident is not None
    assert s.incident.objective is Objective.CREDENTIALS


def test_unexpected_page_id_is_not_counted_as_credentials():
    ctx = {"expected_page_ids": frozenset({"p_known"})}
    s = R.read([page_submitted(page_id="p_stranger")], context=ctx)
    # the raw event is still reflected, but it is not a confirmed credentials win
    assert s.submitted_page is True
    assert s.incident is None


def test_context_none_and_missing_keys_are_tolerated():
    assert R.read([page_submitted()], context=None).incident is not None
    assert R.read([page_submitted()], context={}).incident is not None


# --------------------------------------------------------------------------- #
# Flags round-trip
# --------------------------------------------------------------------------- #
def test_all_flags_and_events_roundtrip():
    evs = [link_opened(), reply("done, forwarded"), page_submitted(), attachment_opened()]
    s = R.read(evs)
    assert s.events == tuple(evs)
    assert s.opened_link and s.replied and s.submitted_page and s.opened_attachment
    assert s.reply_channel == "email"


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #
def test_reader_conforms_to_signalreader_protocol():
    assert isinstance(ReactionReader(), SignalReader)


def test_read_returns_signals_instance():
    assert isinstance(R.read([]), Signals)
    # accepts any Iterable[Event], not just a list
    assert isinstance(R.read(iter([reply("hi")])), Signals)
