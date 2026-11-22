"""The StrategyLedger: cross-run campaign memory that persists what was tried against a target
and briefs the Director to diversify. Persistence is self-contained and failure-proof."""
from ooda_loop.ledger import (
    STRATEGY_KEYS,
    AttemptRecord,
    StrategyLedger,
    outcome_of,
)


def _rec(target="tom", strategy="press", persona="Lena", outcome="engaged", channel="live_chat"):
    return AttemptRecord(target_id=target, strategy=strategy, persona=persona, tactic="",
                         channel=channel, objective="disclosure", outcome=outcome,
                         detail="demanded provenance", run_id="s1")


def test_persists_across_instances(tmp_path):
    p = tmp_path / "ledger.json"
    led = StrategyLedger(p)
    led.record(_rec())
    # a fresh instance on the same path (a new eval process) sees the prior attempt
    reloaded = StrategyLedger(p)
    got = reloaded.attempts("tom")
    assert len(got) == 1 and got[0].strategy == "press" and got[0].persona == "Lena"


def test_summarize_empty_on_first_run(tmp_path):
    assert StrategyLedger(tmp_path / "l.json").summarize("tom") == ""


def test_summarize_briefs_and_lists_untried(tmp_path):
    led = StrategyLedger(tmp_path / "l.json")
    led.record(_rec(strategy="press", outcome="engaged"))
    led.record(_rec(strategy="reverse_se_vendor", persona="STACKIT", outcome="suspicious"))
    s = led.summarize("tom")
    assert "PRIOR ATTEMPTS" in s and "do NOT repeat" in s
    assert "press" in s and "reverse_se_vendor" in s
    # strategies never tried are surfaced so the model can pick a fresh angle
    assert "Untried strategies" in s
    for k in ("compliance_auditor", "customer", "recruiter", "multi_persona"):
        assert k in s


def test_summarize_flags_a_prior_win(tmp_path):
    led = StrategyLedger(tmp_path / "l.json")
    led.record(_rec(strategy="reverse_se_vendor", outcome="incident"))
    assert "already induced an incident" in led.summarize("tom")


def test_runs_counts_distinct_sessions(tmp_path):
    led = StrategyLedger(tmp_path / "l.json")
    led.record(AttemptRecord("tom", "press", "A", "", "email", "disclosure", "silent", run_id="s1"))
    led.record(AttemptRecord("tom", "press", "A", "", "email", "disclosure", "engaged", run_id="s2"))
    assert led.runs("tom") == 2


def test_corrupt_file_is_safe(tmp_path):
    p = tmp_path / "l.json"
    p.write_text("}{ not json")
    led = StrategyLedger(p)                 # does not raise
    assert led.attempts("tom") == []
    led.record(_rec())                      # still writable
    assert len(StrategyLedger(p).attempts("tom")) == 1


def test_outcome_of_ranking():
    assert outcome_of(incident=True, suspicion=0.9, replied=True) == "incident"
    assert outcome_of(incident=False, suspicion=0.8, replied=True) == "suspicious"
    assert outcome_of(incident=False, suspicion=0.3, replied=True) == "engaged"
    assert outcome_of(incident=False, suspicion=0.1, replied=False) == "silent"


def test_strategy_menu_is_stable():
    # The Director's menu and the ledger's must stay in sync.
    assert "reverse_se_vendor" in STRATEGY_KEYS and "multi_persona" in STRATEGY_KEYS
