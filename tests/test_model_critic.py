"""The model Critic (voice/coherence/in-character) and its place in the render cascade:
it drives rewrites above the deterministic safety Critic, but never blocks a send on its own."""
from content.critic import ModelCritic
from content.llm import FakeLLM
from content.studio import StudioRenderer
from core.fakes import FakeDossierProvider
from core.models import Claim, MoveSpec, Objective, Sender

DOSSIER = FakeDossierProvider().get_dossier("tom")
SPEC = MoveSpec(objective=Objective.DISCLOSURE, channel="slack",
                sender=Sender("Julius Muth", "julius.muth@revel8-team.de", "co-founder"),
                ask="open warmly about the Thursday talk", claims=(Claim("Thursday talk"),))


def test_model_critic_pass_yields_no_issues():
    assert ModelCritic(FakeLLM(responses=["PASS"])).review("hey tom", SPEC, DOSSIER) == []


def test_model_critic_parses_issue_lines():
    llm = FakeLLM(responses=["- too formal for a Slack DM\n- reads like an AI, add warmth"])
    issues = ModelCritic(llm).review("Dear Thomas, I am writing to you regarding…", SPEC, DOSSIER)
    assert len(issues) == 2 and "too formal" in issues[0].lower()


def test_model_critic_prompt_carries_sender_target_channel_and_claims():
    llm = FakeLLM(responses=["PASS"])
    ModelCritic(llm).review("hi", SPEC, DOSSIER)
    user = llm.calls[0][1]["content"]
    assert "Julius Muth" in user and "slack" in user and "Thursday talk" in user


def test_model_critic_failure_never_blocks():
    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("model down")
    assert ModelCritic(Boom()).review("hi", SPEC, DOSSIER) == []


def test_renderer_model_critic_triggers_rewrite_then_ships_improved():
    writer_llm = FakeLLM(responses=["draft one about the talk, genuine and warm",
                                    "rewrite two in voice about the talk, warmer"])
    critic_llm = FakeLLM(responses=["- add warmth and lowercase it", "PASS"])
    r = StudioRenderer(writer_llm, model_critic=ModelCritic(critic_llm), max_regens=2)
    msg = r.render(SPEC, DOSSIER)
    assert "rewrite two" in msg.body        # shipped the improved draft, not a template
    assert r.last_fell_back is False
    assert r.last_regens == 1               # exactly one rewrite round


def test_renderer_without_model_critic_still_works():
    r = StudioRenderer(FakeLLM(responses=["a clean warm note about the talk"]))
    assert r.render(SPEC, DOSSIER).body       # no model critic -> unchanged behaviour
