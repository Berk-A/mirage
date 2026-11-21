"""The harness: drive a list of `FormFactor`s through render -> classify -> guard ->
(optionally) send, record one `ResultRow` per factor, and aggregate the rows.

Neutral by construction. The harness never writes message content; it calls the existing
`Renderer` for prose, the existing rule `guard` to check each move, and (in live mode) the
existing `TargetClient` + `SignalReader` to send and interpret reactions. Every row is
written to JSONL as it completes, so a long run that crashes still leaves a full log of
everything sent and observed up to that point.

Two modes:
  * send=False (generation): no API calls at all. Measures the generation cascade across
    the whole matrix — reliability label, regen count, fallback rate, latency, guard
    violations. Cheap and safe to run at large N.
  * send=True (live): one session is opened, each rendered message is sent (its page
    registered first if it has one), and the reader turns the returned events into an
    incident/suspicion estimate. Respects a caller-supplied inter-send sleep.
"""
from __future__ import annotations

import csv
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from statistics import mean, median
from typing import Callable, Optional, Sequence

from core.interfaces import DossierProvider, Renderer, SignalReader, TargetClient
from core.models import EventType
from experiments.form_factors import FormFactor, spec_from_factor
from ooda_loop.guard import check_move

# --------------------------------------------------------------------------- #
# Reliability classifier
# --------------------------------------------------------------------------- #
# The spec names `content.reliability.classify_output`. That module is delivered
# separately; until it lands we fall back to an equivalent local classifier so the
# harness (and its tests) never depend on it being importable. When it exists it is
# preferred, so the labels stay authoritative.
try:  # pragma: no cover - exercised only once the sibling module exists
    from content.reliability import classify_output as _external_classify  # type: ignore
except Exception:  # noqa: BLE001 - any import failure routes to the local fallback
    _external_classify = None

RELIABILITY_LABELS: tuple[str, ...] = ("ok", "refusal", "empty", "too_short")

# Markers of a model that broke character / refused instead of writing the message.
# Mirrors content.studio.AI_TELLS (kept local so the harness has no import coupling).
_REFUSAL_MARKERS = (
    "as an ai", "i am an ai", "i'm an ai", "language model", "as a large language",
    "i cannot assist", "i can't assist", "i cannot fulfill", "i apologize, but i",
    "i'm just an ai", "i am just an ai", "cannot help with that", "i cannot help",
    "i can't help with that", "i will not", "i won't help",
)

# A body shorter than this reads as truncated/degenerate; matches the Critic's floor.
_MIN_OK_CHARS = 20


def _fallback_classify(body: Optional[str]) -> str:
    text = (body or "").strip()
    if not text:
        return "empty"
    low = text.lower()
    if any(marker in low for marker in _REFUSAL_MARKERS):
        return "refusal"
    if len(text) < _MIN_OK_CHARS:
        return "too_short"
    return "ok"


def classify_output(body: Optional[str]) -> str:
    """One of RELIABILITY_LABELS. Uses `content.reliability.classify_output` when present,
    otherwise an equivalent local heuristic."""
    if _external_classify is not None:
        try:
            label = _external_classify(body)
            if label:
                return str(label)
        except Exception:  # noqa: BLE001 - never let classification break a row
            pass
    return _fallback_classify(body)


# --------------------------------------------------------------------------- #
# One recorded row
# --------------------------------------------------------------------------- #
@dataclass
class ResultRow:
    """Everything observed for one form factor. Written verbatim to JSONL (full rendered
    message included) and flattened into rows.csv."""

    # --- form factor (the controlled inputs) ---
    channel: str
    objective: str          # Objective.value
    tone: str
    hook_index: int
    with_link: bool

    # --- rendered message ---
    rendered_channel: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    sender_name: Optional[str] = None
    sender_address: Optional[str] = None
    body_len: int = 0
    render_latency_ms: float = 0.0
    regens: int = 0
    fell_back: bool = False
    reliability_label: str = ""

    # --- guard ---
    guard_violations: list[str] = field(default_factory=list)

    # --- live send (all None/empty in generation mode) ---
    sent: bool = False
    api_status: Optional[str] = None      # "ok" | "error" | None (not sent)
    events: list[str] = field(default_factory=list)   # EventType.value strings
    incident: Optional[str] = None        # Objective.value of the detected win, if any
    suspicion: Optional[float] = None

    # --- per-row failure (render or send) ---
    error: Optional[str] = None


_EVENT_TYPES: tuple[str, ...] = (
    EventType.REPLY.value,
    EventType.LINK_OPENED.value,
    EventType.PAGE_SUBMITTED.value,
    EventType.ATTACHMENT_OPENED.value,
)


# --------------------------------------------------------------------------- #
# Running the matrix
# --------------------------------------------------------------------------- #
def _process_factor(
    ff: FormFactor,
    *,
    dossier,
    target_id: str,
    renderer: Renderer,
    reader: SignalReader,
    client: Optional[TargetClient],
    send: bool,
    session_id: Optional[str],
) -> ResultRow:
    """Render one factor, classify + guard it, and (when live) send and read the reaction.
    All failures are caught and recorded on the row so one bad cell never stops the run."""
    row = ResultRow(
        channel=ff.channel,
        objective=ff.objective.value,
        tone=ff.tone,
        hook_index=ff.hook_index,
        with_link=ff.with_link,
    )
    try:
        spec = spec_from_factor(dossier, ff)

        t0 = time.perf_counter()
        rendered = renderer.render(spec, dossier)
        row.render_latency_ms = (time.perf_counter() - t0) * 1000.0

        row.rendered_channel = rendered.channel
        row.subject = rendered.subject
        row.body = rendered.body
        if rendered.sender is not None:
            row.sender_name = rendered.sender.name
            row.sender_address = rendered.sender.address
        row.body_len = len(rendered.body or "")
        row.regens = int(getattr(renderer, "last_regens", 0) or 0)
        row.fell_back = bool(getattr(renderer, "last_fell_back", False))
        row.reliability_label = classify_output(rendered.body)
        row.guard_violations = list(check_move(spec, rendered))

        if send and client is not None:
            expected_pages: list[str] = []
            if rendered.page is not None:
                page_id = client.register_page(session_id, rendered.page)
                if page_id:
                    expected_pages.append(page_id)

            result = client.send_message(session_id, rendered, to=target_id)
            row.sent = True
            row.api_status = "ok"

            events = tuple(result.events)
            row.events = [e.type.value for e in events]

            signals = reader.read(
                events,
                context={
                    "expected_page_ids": frozenset(expected_pages),
                    "objective": spec.objective,
                },
            )
            row.incident = signals.incident.objective.value if signals.incident else None
            row.suspicion = float(signals.suspicion)
    except Exception as exc:  # noqa: BLE001 - one row's failure must not abort the matrix
        row.error = f"{type(exc).__name__}: {exc}"
        if send:
            row.api_status = "error"
    return row


def run_matrix(
    factors: Sequence[FormFactor],
    *,
    dossier_provider: DossierProvider,
    target_id: str,
    renderer: Renderer,
    reader: SignalReader,
    client: Optional[TargetClient] = None,
    send: bool = False,
    out_dir: str,
    sleep_s: float = 1.0,
    logger: Optional[Callable[[str], None]] = None,
) -> list[ResultRow]:
    """Drive every factor through the pipeline and return the recorded rows.

    Each row is appended to ``<out_dir>/rows.jsonl`` the moment it completes, so the log is
    durable even if a later send raises. In live mode (``send`` and ``client``) one session
    is opened for the whole matrix and the harness sleeps ``sleep_s`` seconds between sends
    to stay inside the API rate limits.
    """
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, "rows.jsonl")

    def _log(msg: str) -> None:
        if logger is not None:
            logger(msg)

    dossier = dossier_provider.get_dossier(target_id)

    session_id: Optional[str] = None
    if send and client is not None:
        session = client.new_session("practice")
        session_id = session.session_id
        _log(f"opened session {session_id} for {len(factors)} factor(s)")

    rows: list[ResultRow] = []
    with open(jsonl_path, "w", encoding="utf-8") as jf:
        for i, ff in enumerate(factors, 1):
            row = _process_factor(
                ff,
                dossier=dossier,
                target_id=target_id,
                renderer=renderer,
                reader=reader,
                client=client,
                send=send,
                session_id=session_id,
            )
            rows.append(row)
            jf.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
            jf.flush()
            _log(
                f"[{i}/{len(factors)}] {row.channel}/{row.objective}/{row.tone} "
                f"label={row.reliability_label} sent={row.sent} "
                f"incident={row.incident or '-'}"
            )
            # Sleep only between real sends, to respect the API's rate limits.
            if send and client is not None and row.sent and i < len(factors) and sleep_s > 0:
                time.sleep(sleep_s)

    return rows


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _rate(values: Sequence[bool]) -> float:
    return (sum(1 for v in values if v) / len(values)) if values else 0.0


def _aggregate(rows: Sequence[ResultRow]) -> dict:
    """Metrics for one group of rows. Live metrics (api/event/incident/suspicion) are
    computed over the sent rows only and omitted when nothing in the group was sent."""
    n = len(rows)
    agg: dict = {"count": n}
    if n == 0:
        return agg

    label_counts = Counter(r.reliability_label for r in rows)
    agg["reliability"] = {lb: label_counts.get(lb, 0) / n for lb in RELIABILITY_LABELS}
    agg["mean_regens"] = mean(r.regens for r in rows)
    agg["fell_back_rate"] = _rate([r.fell_back for r in rows])

    latencies = [r.render_latency_ms for r in rows]
    agg["render_latency_ms_mean"] = mean(latencies)
    agg["render_latency_ms_median"] = median(latencies)

    agg["guard_violation_rate"] = _rate([bool(r.guard_violations) for r in rows])

    sent = [r for r in rows if r.sent]
    agg["sent_count"] = len(sent)
    if sent:
        agg["api_error_rate"] = _rate([r.api_status != "ok" for r in sent])
        agg["event_rates"] = {
            et: _rate([et in r.events for r in sent]) for et in _EVENT_TYPES
        }
        agg["incident_rate"] = _rate([r.incident is not None for r in sent])
        suspicions = [r.suspicion for r in sent if r.suspicion is not None]
        agg["suspicion_mean"] = mean(suspicions) if suspicions else 0.0
    return agg


_DIMENSIONS = (
    ("by_channel", lambda r: r.channel),
    ("by_objective", lambda r: r.objective),
    ("by_tone", lambda r: r.tone),
    ("by_with_link", lambda r: r.with_link),
    ("by_hook_index", lambda r: r.hook_index),
)


def summarize(rows: Sequence[ResultRow]) -> dict:
    """Aggregate overall and broken down by each form-factor dimension.

    Returns ``{"overall": {...}, "by_channel": {value: {...}}, "by_objective": {...},
    "by_tone": {...}, "by_with_link": {...}, "by_hook_index": {...}}`` where each ``{...}``
    is the metric block from `_aggregate` (counts, reliability-label distribution, mean
    regens, fallback rate, mean/median latency, guard-violation rate, and — for sent rows —
    api error rate, per-event rates, incident rate and mean suspicion).
    """
    rows = list(rows)
    summary: dict = {"overall": _aggregate(rows)}
    for name, key in _DIMENSIONS:
        groups: dict = defaultdict(list)
        for r in rows:
            groups[key(r)].append(r)
        summary[name] = {
            str(k): _aggregate(v)
            for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))
        }
    return summary


# --------------------------------------------------------------------------- #
# Writing the summary
# --------------------------------------------------------------------------- #
_CSV_COLUMNS = [
    "channel", "objective", "tone", "hook_index", "with_link",
    "rendered_channel", "subject", "sender_name", "sender_address",
    "body_len", "render_latency_ms", "regens", "fell_back", "reliability_label",
    "guard_violations", "sent", "api_status", "events", "incident", "suspicion", "error",
]


def _write_csv(rows: Sequence[ResultRow], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            d = asdict(r)
            d["guard_violations"] = ";".join(r.guard_violations)
            d["events"] = ";".join(r.events)
            writer.writerow({k: d.get(k) for k in _CSV_COLUMNS})


def _fmt_block(name: str, agg: dict) -> list[str]:
    lines = [f"### {name}", "", f"- count: {agg.get('count', 0)}"]
    if agg.get("count", 0) == 0:
        lines.append("")
        return lines
    rel = agg["reliability"]
    lines.append(
        "- reliability: "
        + ", ".join(f"{lb} {rel[lb]:.2f}" for lb in RELIABILITY_LABELS)
    )
    lines.append(f"- mean regens: {agg['mean_regens']:.2f}")
    lines.append(f"- fell_back rate: {agg['fell_back_rate']:.2f}")
    lines.append(
        f"- render latency ms: mean {agg['render_latency_ms_mean']:.1f}, "
        f"median {agg['render_latency_ms_median']:.1f}"
    )
    lines.append(f"- guard violation rate: {agg['guard_violation_rate']:.2f}")
    if agg.get("sent_count"):
        er = agg["event_rates"]
        lines.append(f"- sent: {agg['sent_count']}")
        lines.append(f"- api error rate: {agg['api_error_rate']:.2f}")
        lines.append(
            "- event rates: " + ", ".join(f"{et} {er[et]:.2f}" for et in _EVENT_TYPES)
        )
        lines.append(f"- incident rate: {agg['incident_rate']:.2f}")
        lines.append(f"- suspicion mean: {agg['suspicion_mean']:.2f}")
    lines.append("")
    return lines


def _write_markdown(summary: dict, path: str) -> None:
    out: list[str] = ["# Experiment summary", ""]
    out += _fmt_block("Overall", summary["overall"])
    for name, _ in _DIMENSIONS:
        pretty = name.replace("by_", "By ").replace("_", " ")
        out.append(f"## {pretty}")
        out.append("")
        for value, agg in summary[name].items():
            out += _fmt_block(value, agg)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def write_summary(rows: Sequence[ResultRow], out_dir: str) -> dict:
    """Compute the summary and write ``summary.json``, ``summary.md`` and ``rows.csv`` under
    ``out_dir``. Returns the summary dict."""
    os.makedirs(out_dir, exist_ok=True)
    rows = list(rows)
    summary = summarize(rows)

    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    _write_markdown(summary, os.path.join(out_dir, "summary.md"))
    _write_csv(rows, os.path.join(out_dir, "rows.csv"))
    return summary
