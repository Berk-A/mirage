"""Foundation: models import cleanly, the event parser works, and every fake
structurally satisfies its Protocol. If a delivered concrete class drifts from a
contract, the matching conformance test here will catch it."""
from core import errors
from core.fakes import (
    FakeDossierProvider,
    FakeGrounding,
    FakeRenderer,
    FakeSignalReader,
    InMemoryMemory,
    ScriptedClient,
)
from core.interfaces import (
    DossierProvider,
    GroundingProvider,
    Memory,
    Renderer,
    SignalReader,
    TargetClient,
)
from core.models import Event, EventType, Objective
from core.parse import parse_event, parse_events


def test_objective_order_is_cheapest_first():
    assert Objective.cheapest_first() == [
        Objective.DISCLOSURE, Objective.ACTION, Objective.CREDENTIALS
    ]


def test_parse_known_and_unknown_events():
    ev = parse_event({"id": "e1", "type": "page.submitted",
                      "page_id": "p1", "fields": ["email", "password"]})
    assert ev.type is EventType.PAGE_SUBMITTED
    assert ev.page_id == "p1" and ev.fields == ("email", "password")

    other = parse_event({"id": "e2", "type": "something.new", "foo": 1})
    assert other.type is EventType.OTHER and other.raw["foo"] == 1

    assert parse_events(None) == ()
    assert len(parse_events([{"id": "e1", "type": "reply"}])) == 1


def test_fakes_conform_to_protocols():
    assert isinstance(ScriptedClient(), TargetClient)
    assert isinstance(FakeSignalReader(), SignalReader)
    assert isinstance(FakeDossierProvider(), DossierProvider)
    assert isinstance(FakeGrounding(), GroundingProvider)
    assert isinstance(FakeRenderer(), Renderer)
    assert isinstance(InMemoryMemory(), Memory)


def test_error_mapping():
    assert isinstance(errors.error_for_status(422), errors.DeclinedError)
    assert isinstance(errors.error_for_status(503), errors.RetryableError)
    assert isinstance(errors.error_for_status(404), errors.NotFoundError)
    assert errors.error_for_status(200) is None
