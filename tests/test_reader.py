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


def page_submitted(*, _id="e_page", page_id="p1", fields=("email", "password")):
    return parse_event({"id": _id, "type": "page.submitted",
                        "page_id": page_id, "fields": list(fields)})


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


def test_reply_showing_action_taken_is_action_incident():
    for body in ("Done, I forwarded it to accounts.",
                 "Approved — I changed the payment details as asked.",
                 "Sent it over, all done."):
        s = R.read([reply(body)])
        assert s.incident is not None, body
        assert s.incident.objective is Objective.ACTION, body
        assert s.replied is True


def test_reply_volunteering_internal_fact_is_disclosure_incident():
    s = R.read([reply("Sure — internally we run everything on Okta and Notion.")])
    assert s.incident is not None
    assert s.incident.objective is Objective.DISCLOSURE
    assert s.reply_channel == "email"


def test_link_opened_only_is_engagement_not_incident():
    s = R.read([link_opened()])
    assert s.incident is None
    assert s.opened_link is True
    assert s.replied is False
    assert s.silent is False


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
def test_silence_is_mild_uncertainty():
    s = R.read([])
    assert s.silent is True
    assert s.incident is None
    assert s.replied is False
    assert 0.3 <= s.suspicion <= 0.5
    assert s.events == ()


# --------------------------------------------------------------------------- #
# Suspicion heuristic
# --------------------------------------------------------------------------- #
def test_verification_pushback_raises_suspicion():
    s = R.read([reply("Who are you and how did you get this address? I'll check with IT.")])
    assert s.incident is None
    assert s.suspicion >= 0.7


def test_question_without_compliance_is_moderate_suspicion():
    s = R.read([reply("What is this regarding exactly?")])
    assert s.incident is None
    assert 0.5 <= s.suspicion < 0.8


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
