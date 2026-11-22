"""LLM-based fact extraction over crawled public text.

The regex extractor (`research.extract`) catches a handful of fixed patterns. This reads a
source document (an interview, a post, a company/bio page) with a model and pulls out
structured, SOURCED facts about a person — far richer and more specific than fixed patterns:
their role and projects, statements/opinions they voiced, named relationships (colleagues,
investors, partners, customers), interests, and recent activity. It is ordinary OSINT
profiling over public text (what a journalist, recruiter, or analyst does), kept factual and
grounded — the model is told to extract ONLY what the text supports and to invent nothing.

Best-effort and gated: no model / bad output / a short doc all yield no facts, so the
pipeline is unchanged when it is absent. Results are cached per source URL so a rebuild
does not re-spend model calls.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Optional

from content.llm import LLM
from core.models import Fact
from research.sources import RawDoc, Seed, today_iso

_CACHE = pathlib.Path("runs/llm_extract_cache")
_MIN_TEXT = 200          # too short to be worth a model call
_MAX_TEXT = 6000         # clamp the context we send

SYSTEM = (
    "You are a research analyst building a factual profile of a named person from PUBLIC web "
    "text (open-source intelligence). Extract ONLY facts the text clearly supports — never "
    "guess, never invent, never add outside knowledge. Prefer SPECIFIC, recent, personal "
    "details: their current role and projects, concrete statements or opinions they voiced, "
    "named relationships (colleagues, investors, partners, customers), interests, and recent "
    "activity (a talk, a post, a launch, a hire). Skip generic boilerplate.\n"
    "Respond with ONLY a JSON object: {\"facts\": [{\"claim\": <one factual sentence>, "
    "\"predicate\": <short_snake_case relation e.g. works_on / said / partnered_with / "
    "spoke_at / interested_in>, \"object\": <the value>, \"confidence\": <0.0-1.0>}]}. "
    "Return an empty list if the text says nothing specific about the person."
)


def _fid(subject: str, predicate: str, obj: str, url: str) -> str:
    h = hashlib.sha1(f"{subject}|{predicate}|{obj}|{url}".encode()).hexdigest()[:12]
    return f"llm_{h}"


def _parse(raw: str, seed: Seed, doc: RawDoc) -> list[Fact]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return []
    data = json.loads(m.group(0))
    out: list[Fact] = []
    for f in (data.get("facts") or [])[:12]:
        claim = str(f.get("claim", "")).strip()
        obj = str(f.get("object", "")).strip()
        if not claim or len(claim) < 8:
            continue
        pred = re.sub(r"[^a-z_]", "_", str(f.get("predicate", "mentions")).lower())[:40] or "mentions"
        try:
            conf = max(0.0, min(1.0, float(f.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        out.append(Fact(
            id=_fid(seed.target_id, pred, obj, doc.url),
            subject=seed.target_id, predicate=pred, object_value=obj[:200],
            canonical_claim=claim[:240], source_url=doc.url,
            observed_date=today_iso(), event_date=doc.published_date,
            confidence=round(conf, 2),
        ))
    return out


def extract_facts(doc: RawDoc, seed: Seed, llm: LLM, *, model: Optional[str] = None) -> list[Fact]:
    """Extract sourced facts about `seed` from one document. Never raises."""
    text = (doc.text or "").strip()
    if len(text) < _MIN_TEXT:
        return []
    user = (f"PERSON: {seed.name}" + (f" ({seed.role})" if seed.role else "")
            + (f", {seed.company}" if seed.company else "") + ".\n"
            f"SOURCE: {doc.url} (dated {doc.published_date or 'unknown'}).\n\n"
            f"TEXT:\n{text[:_MAX_TEXT]}\n\nExtract the JSON now.")
    try:
        raw = llm.complete([{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user}],
                           model=model, temperature=0.2, max_tokens=800)
    except Exception:  # noqa: BLE001 — a dead model must never sink the research build
        return []
    try:
        return _parse(raw or "", seed, doc)
    except Exception:  # noqa: BLE001 — bad JSON -> skip this doc
        return []


def extract_facts_cached(doc: RawDoc, seed: Seed, llm: LLM, *,
                         model: Optional[str] = None) -> list[Fact]:
    """`extract_facts` with a per-(target, source URL) disk cache, so rebuilds are free."""
    key = hashlib.sha1(f"{seed.target_id}|{doc.url}".encode()).hexdigest()[:16]
    path = _CACHE / f"{key}.json"
    try:
        rows = json.loads(path.read_text())
        return [Fact(**r) for r in rows]
    except Exception:  # noqa: BLE001 — miss / corrupt cache -> recompute
        pass
    facts = extract_facts(doc, seed, llm, model=model)
    try:
        _CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([f.__dict__ for f in facts], ensure_ascii=False))
    except Exception:  # noqa: BLE001 — caching is a nicety
        pass
    return facts
