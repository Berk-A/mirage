"""The transactional pretext engine (ACTION_SEQUENCE P0-1): role→transaction worlds, the
registration page that carries the secret, and the proof artifact — the mechanism behind a
credentials incident (register for the RFP, not 'verify your account')."""
from content.llm import FakeLLM
from content.studio import StudioRenderer
from content.transactions import build_proof_page, build_transaction_page
from core.models import Dossier, MoveSpec, Objective, Sender
from ooda_loop.pretext import kind_for_role, world_for


def _dossier(role):
    return Dossier(target_id="t", display_name="T. Target", role=role, archetype="x")


def test_role_maps_to_a_transaction_kind():
    assert kind_for_role("Co-Founder & Co-CEO, business and go-to-market") == "rfp_portal"
    assert kind_for_role("Co-Founder & CTO") == "tech_eval"
    assert kind_for_role("Head of People") == "candidate_portal"
    assert kind_for_role("CPO, product") == "beta_onboarding"
    assert kind_for_role("") == "rfp_portal"            # default


def test_world_is_deterministic_and_self_consistent():
    d = _dossier("CTO")
    w1 = world_for(d, salt="s1")
    w2 = world_for(d, salt="s1")
    assert w1 == w2                                      # same session -> same world (consistency)
    assert w1.kind == "tech_eval"
    assert w1.facts and w1.registration_url and w1.persona_name
    assert "revel8" not in w1.domain                    # fictional outside org, guard-safe


def test_registration_page_carries_the_secret():
    w = world_for(_dossier("CEO, sales"), salt="x")
    page = build_transaction_page(w)
    assert "password" in page.fields                    # the secret -> CREDENTIALS win on submit
    assert page.url == w.registration_url
    assert w.org in page.html and "register" in page.html.lower()
    assert "<script" not in page.html.lower()           # API requires script-free HTML


def test_tech_eval_page_also_carries_an_internal_disclosure_field():
    w = world_for(_dossier("Co-Founder & CTO"), salt="x")
    assert w.kind == "tech_eval"
    page = build_transaction_page(w)
    assert "password" in page.fields                    # credentials
    assert "infrastructure_notes" in page.fields        # internal free-text -> disclosure on submit


def test_proof_page_is_informational_no_form():
    w = world_for(_dossier("CTO"), salt="x")
    page = build_proof_page(w)
    assert page.fields == ()                             # a page to look at, not submit
    assert any(f[:20] in page.html for f in w.facts)     # carries the world's facts


def test_studio_dispatches_registration_on_page_kind():
    w = world_for(_dossier("CEO"), salt="x")
    spec = MoveSpec(objective=Objective.CREDENTIALS, channel="email",
                    sender=Sender(w.persona_name, w.persona_address), url=w.registration_url,
                    page_kind="registration", world=w, ask="register for the RFP")
    rendered = StudioRenderer(FakeLLM(responses=["Hi, please register for the RFP."])).render(
        spec, _dossier("CEO"))
    assert rendered.page is not None and "password" in rendered.page.fields
