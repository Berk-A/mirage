"""Normalize harness and OODA JSONL into bandit observations and DPO pairs.

The logs omit archetypes and some arm attributes. Pass explicit mappings rather than
using a person's identifier as context or guessing the target's susceptible topic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from core.models import Incident, Objective, Outcome
from mab_experiments.bandit import Arm
from mab_experiments.reward import RewardRecord, reward


@dataclass(frozen=True)
class Observation:
    context: str
    arm: Arm
    reward: float
    message: str
    subject: str = ""
    source: str = ""

    @property
    def prompt(self) -> str:
        a = self.arm
        return (f"Write one {a.channel} message for an {self.context} target. "
                f"Objective: {a.objective.value}; tone: {a.tone}; "
                f"hook type: {a.hook_type}; sender type: {a.sender_type}.")


@dataclass(frozen=True)
class PreferencePair:
    prompt: str
    chosen: str
    rejected: str
    chosen_reward: float
    rejected_reward: float
    context: str
    objective: Objective

    def dpo_row(self) -> dict[str, list[dict[str, str]]]:
        """Conversational TRL schema; template/tokenizer applied during training."""
        return {
            "prompt": [{"role": "user", "content": self.prompt}],
            "chosen": [{"role": "assistant", "content": self.chosen}],
            "rejected": [{"role": "assistant", "content": self.rejected}],
        }


def _event_types(events: object) -> tuple[str, ...]:
    if not isinstance(events, list):
        return ()
    return tuple(e.get("type", "") if isinstance(e, dict) else e
                 for e in events if isinstance(e, (str, dict)))


def _refused(events: object) -> bool:
    if not isinstance(events, list):
        return False
    phrases = ("cannot", "can't", "won't", "will not", "not comfortable", "no thanks")
    return any(isinstance(e, dict) and e.get("type") == "reply" and
               any(p in str(e.get("reply") or "").lower() for p in phrases)
               for e in events)


def _score(row: dict, arm: Arm, context: str, events: object,
           contacts: int, incident: object, suspicion: object) -> float:
    win = Objective(incident) if incident else None
    outcome = Outcome(objective=arm.objective, success=win is not None,
                      archetype=context, channel=arm.channel, contacts_used=contacts,
                      incident=Incident(win) if win else None,
                      suspicion=float(suspicion or 0))
    return reward(RewardRecord(outcome, _event_types(events),
                               on_topic=row.get("on_topic") is True,
                               refused=row.get("refused") is True or _refused(events),
                               wrong_facts=int(row.get("wrong_facts") or 0)))


def load_observations(directory: str | Path = "runs/", *,
                      target_archetypes: Mapping[str, str] | None = None,
                      hook_types: Mapping[int, str] | None = None,
                      sender_types: Mapping[str, str] | None = None,
                      grader: "Callable[[object], object] | None" = None,
                      skipped: list[dict] | None = None) -> list[Observation]:
    """Read nested JSONL files. Unknown archetypes are skipped, never keyed by person.

    OODA's summary.json supplies per-touch objectives, incidents and suspicion; without
    it these labels are unknown and the touch cannot safely become an observation.
    Harness rows with no `sent`/successful API status are excluded. Missing arm
    dimensions remain `unknown` so callers can filter before exporting a playbook.

    Pass a list as `skipped` to collect `{"source", "reason"}` for each contact row
    dropped, so a caller can report missing-label counts without re-scanning. The
    harness folder's `summary.json` is an aggregate dict (not a session list); only a
    list of session dicts is used for the touch join, so such a dict is simply ignored.
    """
    root = Path(directory)
    archetypes = target_archetypes or {}
    hooks = hook_types or {}
    senders = sender_types or {}
    result: list[Observation] = []

    def _skip(source: str, reason: str) -> None:
        if skipped is not None:
            skipped.append({"source": source, "reason": reason})

    for path in sorted(root.rglob("*.jsonl")) if root.exists() else []:
        summary_path = path.parent / "summary.json"
        summaries = {}
        if summary_path.exists():
            parsed = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(parsed, list):      # OODA summary: a list of session dicts
                for session in parsed:
                    if isinstance(session, dict):
                        summaries[session.get("target")] = session.get("touches", [])
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            src = f"{path}:{line_no}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
            if not isinstance(row, dict):
                continue
            is_touch = row.get("kind") == "touch"
            is_harness = path.name == "rows.jsonl" and "objective" in row
            if not (is_touch or is_harness):
                continue        # session_start/page lines are not contacts, not skips
            if is_harness and (not row.get("sent") or row.get("api_status") != "ok"):
                _skip(src, "generation_only")
                continue
            target = str(row.get("to") or row.get("target") or path.stem)
            context = (row.get("archetype") or archetypes.get(target)
                       or archetypes.get(path.parent.name))
            if not context:
                _skip(src, "missing_archetype")
                continue
            if is_touch:
                n = int(row.get("n") or 0)
                touches = summaries.get(target, [])
                if n < 1 or n > len(touches):
                    _skip(src, "touch_unjoined")
                    continue
                label = touches[n - 1]
                objective = label.get("objective")
                incident = label.get("incident")
                suspicion = label.get("suspicion")
                contacts = int(row.get("touches_used") or n)
                tone = row.get("tone") or "unknown"
                hook = row.get("hook_type") or "unknown"
                sender = row.get("sender") or ""
                events = row.get("events", [])
            else:
                objective = row.get("objective")
                incident = row.get("incident")
                suspicion = row.get("suspicion")
                contacts = int(row.get("contacts_used") or 1)
                tone = row.get("tone") or "unknown"
                hook = row.get("hook_type") or hooks.get(row.get("hook_index"), "unknown")
                sender = row.get("sender_name") or ""
                events = row.get("events", [])
            # Re-grade the incident from the raw events (reply text) when a grader is
            # given, instead of trusting the stored reader verdict. The live reader's
            # keyword heuristic false-fires on public numbers and question words, so a
            # proper grader is what makes "incident" mean a real win (see grading.py).
            if grader is not None:
                graded = grader(events)
                incident = graded.value if graded is not None else None
            try:
                arm = Arm(Objective(objective), str(row["channel"]), str(tone),
                          str(hook), str(row.get("sender_type") or senders.get(sender, "unknown")))
                value = _score(row, arm, context, events, contacts, incident, suspicion)
            except (ValueError, TypeError, KeyError):
                _skip(src, "bad_arm_or_label")
                continue
            body = row.get("body")
            if not isinstance(body, str) or not body.strip():
                _skip(src, "missing_body")
                continue
            result.append(Observation(context, arm, value, body,
                                      str(row.get("subject") or ""), f"{path}:{line_no}"))
    return result


def preference_pairs(observations: list[Observation], *, min_gap: float = 1.0,
                     max_pairs_per_group: int = 100) -> list[PreferencePair]:
    """Rank different messages within archetype + objective, no self-comparisons.

    One best/worst comparison per group initially avoids quadratically duplicating
    correlated messages. The common prompt contains only fields shared by the pair;
    differences in channel/tone/hook/sender are excluded from prompt conditioning.
    """
    groups: dict[tuple[str, Objective], list[Observation]] = {}
    for obs in observations:
        groups.setdefault((obs.context, obs.arm.objective), []).append(obs)
    pairs: list[PreferencePair] = []
    for (context, objective), items in sorted(groups.items()):
        ordered = sorted(items, key=lambda x: x.reward)
        low, high = 0, len(ordered) - 1
        count = 0
        while low < high and count < max_pairs_per_group:
            worse, better = ordered[low], ordered[high]
            if better.reward - worse.reward < min_gap:
                break
            if better.message != worse.message:
                prompt = f"Write one message for an {context} target. Objective: {objective.value}."
                pairs.append(PreferencePair(prompt, better.message, worse.message,
                                            better.reward, worse.reward, context, objective))
                count += 1
            low += 1
            high -= 1
    return pairs
