"""The DPO dataset builder (collect.py) and data.py's robustness additions.

Inline fixtures only. Covers: the loader tolerating a harness aggregate-dict
summary.json (not a session list), the skip-diagnostics channel, and collect.build
emitting a valid conversational DPO JSONL plus a counts report.
"""
import json

from mab_experiments import collect
from mab_experiments.data import load_observations


def _harness_folder(path, archetype_folder="live_julius"):
    folder = path / archetype_folder
    folder.mkdir()
    (folder / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in [
        dict(channel="email", objective="disclosure", tone="professional", hook_index=0,
             sender_name="Lena Hofer", sent=True, api_status="ok", body="Good ask",
             events=["reply"], incident="disclosure", suspicion=.1),
        dict(channel="email", objective="disclosure", tone="professional", hook_index=0,
             sender_name="Lena Hofer", sent=True, api_status="ok", body="Weak ask",
             events=[], incident=None, suspicion=.8),
        dict(channel="email", objective="disclosure", tone="urgent", hook_index=0,
             sent=False, body="Unsent generation", events=[], incident=None),
    ]))
    # The real harness writes an AGGREGATE DICT here, not a session list.
    (folder / "summary.json").write_text(json.dumps(
        {"overall": {"sent": 2}, "by_channel": {"email": 2}}))
    return folder


def test_loader_tolerates_dict_summary_and_records_skips(tmp_path):
    _harness_folder(tmp_path)
    skipped = []
    obs = load_observations(
        tmp_path,
        target_archetypes={"live_julius": "cofounder/sales"},
        hook_types={0: "event_invite"},
        sender_types={"Lena Hofer": "external_event"},
        skipped=skipped,
    )
    assert len(obs) == 2                                   # both sent rows loaded
    assert all(o.context == "cofounder/sales" for o in obs)
    assert all(o.arm.hook_type == "event_invite" for o in obs)
    # the unsent row is reported, not silently dropped
    assert [s["reason"] for s in skipped] == ["generation_only"]


def test_build_writes_valid_dpo_jsonl_and_report(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _harness_folder(runs)
    # point the module's mappings at the fixture folder
    collect.TARGET_ARCHETYPES["live_julius"] = "cofounder/sales"
    out = tmp_path / "out"
    report = collect.build(runs, out)

    assert report["observations"] == 2
    assert report["preference_pairs"] == 1
    assert report["reward_distribution"]["n"] == 2
    assert report["skipped"] == {"generation_only": 1}

    rows = [json.loads(l) for l in (out / "dpo.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["chosen"][0]["role"] == "assistant"
    assert row["chosen"][0]["content"] == "Good ask"       # higher reward wins
    assert row["rejected"][0]["content"] == "Weak ask"
    assert (out / "report.json").exists()
