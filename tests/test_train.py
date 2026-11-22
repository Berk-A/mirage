"""The MAB training run: the bandit must beat baselines on held-out twins.

Encodes the success criterion as a regression guard — a smaller, fast configuration
of the same training+evaluation harness run from the CLI.
"""
from mab_experiments import train


def test_bandit_beats_random_and_recovers_the_policy_held_out():
    result = train.run(episodes=9000, trials=1500, seed=7)
    reports = result["reports"]
    bandit, random_, fixed, oracle = (
        reports["bandit"], reports["random"], reports["fixed"], reports["oracle"])

    # 1. the learned policy beats random with disjoint 95% CIs (statistically real)
    assert (bandit["mean_reward"] - bandit["ci95"]
            > random_["mean_reward"] + random_["ci95"])
    # 2. and beats the fixed cheapest-first opener
    assert bandit["mean_reward"] > fixed["mean_reward"] + 1.0
    # 3. it reaches many more incidents than random
    assert bandit["incident_rate"] > 2 * random_["incident_rate"]
    # 4. it recovers the twin's true best objective for most archetypes
    recovered = int(result["recovered_objective"].split("/")[0])
    assert recovered >= 4
    # 5. it does not exceed the oracle (can't beat ground truth)
    assert bandit["mean_reward"] <= oracle["mean_reward"] + 1e-6


def test_training_is_reproducible():
    a = train.run(episodes=4000, trials=800, seed=3)
    b = train.run(episodes=4000, trials=800, seed=3)
    assert a["reports"]["bandit"] == b["reports"]["bandit"]
    assert a["playbook"] == b["playbook"]
