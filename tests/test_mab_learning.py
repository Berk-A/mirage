import json

from core.models import Incident, Objective, Outcome
from mab_experiments.bandit import Arm, ContextualBandit
from mab_experiments.data import load_observations, preference_pairs
from mab_experiments.reward import RewardRecord, reward


def test_reward_monotonicity_and_equal_incidents():
    def record(kind=None, n=1, suspicion=0, **kwargs):
        return RewardRecord(Outcome(Objective.ACTION, bool(kind), contacts_used=n,
                                    suspicion=suspicion,
                                    incident=Incident(kind) if kind else None), **kwargs)
    assert reward(record(Objective.ACTION)) == reward(record(Objective.CREDENTIALS))
    assert reward(record(Objective.ACTION, n=1)) > reward(record(Objective.ACTION, n=4))
    assert reward(record(Objective.ACTION, n=4)) > reward(record())
    assert reward(record(on_topic=True)) > reward(record())
    assert reward(record(events=("reply", "link.opened"))) > reward(record())
    assert reward(record(suspicion=.9, refused=True, wrong_facts=1)) < reward(record())


def test_contextual_bandit_converges_without_identity():
    a = Arm(Objective.DISCLOSURE, "email", "professional", "launch", "colleague")
    b = Arm(Objective.ACTION, "slack", "colleague", "review", "partner")
    bandit = ContextualBandit([a, b], seed=42)
    for context, winner in [("cofounder/sales", a), ("cofounder/product", b)]:
        for _ in range(400):
            arm = bandit.select(context)
            bandit.update(context, arm, 10 if arm == winner else -1)
    assert bandit.playbook() == {"cofounder/product": b, "cofounder/sales": a}
    assert sum(bandit.select("cofounder/sales") == a for _ in range(100)) > 95


def test_loader_both_log_formats_and_pairs(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in [
        dict(channel="email", objective="disclosure", tone="professional", hook_index=0,
             sender_name="Colleague", sent=True, api_status="ok", body="A good question",
             events=["reply"], incident="disclosure", suspicion=.1),
        dict(channel="email", objective="disclosure", tone="professional", hook_index=0,
             sender_name="Colleague", sent=True, api_status="ok", body="A bad question",
             events=[], incident=None, suspicion=.8),
        dict(channel="email", objective="disclosure", tone="urgent", hook_index=0,
             sent=False, body="Unsent", events=[], incident=None),
    ]))
    (run / "founder.jsonl").write_text("\n".join(json.dumps(r) for r in [
        dict(kind="session_start", session_id="s1"),
        dict(kind="page", url="example.test"),
        dict(kind="touch", n=1, to="founder", channel="slack", sender="Colleague",
             body="Try this", events=[{"type": "link.opened"}], touches_used=1),
    ]))
    (run / "summary.json").write_text(json.dumps([{"target": "founder", "touches": [
        {"objective": "action", "incident": None, "suspicion": .2}]}]))
    observations = load_observations(tmp_path, target_archetypes={"rows": "cofounder/sales",
                             "founder": "cofounder/product"}, hook_types={0: "launch"},
                             sender_types={"Colleague": "colleague"})
    assert len(observations) == 3
    assert any(o.arm.hook_type == "launch" for o in observations)
    assert any(o.arm.tone == "unknown" for o in observations)
    pairs = preference_pairs(observations)
    assert len(pairs) == 1
    assert pairs[0].chosen == "A good question"
    assert pairs[0].dpo_row()["chosen"][0]["role"] == "assistant"
