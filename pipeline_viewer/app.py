"""MIRAGE pipeline viewer — see the whole pipeline per run, stage by stage:

  1. Research / Knowledge Graph  — the dossier the agent built about the target
  2. Messages sent               — each OODA touch the agent wrote
  3. Reactions                   — what the target did back (reply / open / submit / silence)

Reads the run artifacts written by `experiments/run_ooda.py` under `runs/`:
  <run>/<target>_dossier.json   (research/KG stage; present for --provider real)
  <run>/<target>.jsonl          (per-touch messages + events)
  <run>/summary.json            (per-target objective / suspicion / incident / stop)

Run:  streamlit run pipeline_viewer/app.py --server.port 8502
"""
from __future__ import annotations

import json
import pathlib

import streamlit as st

REPO = pathlib.Path(__file__).resolve().parent.parent
RUNS = REPO / "runs"

st.set_page_config(page_title="MIRAGE pipeline viewer", layout="wide")


def load_json(p: pathlib.Path):
    try:
        return json.loads(_read_text(p))
    except Exception:
        return None


def load_jsonl(p: pathlib.Path) -> list[dict]:
    rows = []
    try:
        for line in _read_text(p).splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except Exception:
        pass
    return rows


def _read_text(p: pathlib.Path) -> str:
    """Read new UTF-8 artifacts and older Windows-code-page run files."""
    try:
        return p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return p.read_text(encoding="cp1252")


def run_dirs() -> list[pathlib.Path]:
    if not RUNS.exists():
        return []
    out = []
    for d in sorted(RUNS.iterdir(), reverse=True):
        if d.is_dir() and (list(d.glob("*.jsonl")) or (d / "summary.json").exists()):
            out.append(d)
    return out


def targets_in(run: pathlib.Path) -> list[str]:
    names = {p.stem for p in run.glob("*.jsonl")}
    names |= {p.name[: -len("_dossier.json")] for p in run.glob("*_dossier.json")}
    return sorted(names)


def susp_color(s: float) -> str:
    return "#1a7f37" if s < 0.35 else ("#9a6700" if s < 0.7 else "#cf222e")


# --------------------------------------------------------------------------- #
st.title("🛰️ MIRAGE — full-pipeline viewer")
st.caption("Research → Knowledge Graph → Messages → Reactions, per run. revel8 sandbox.")

runs = run_dirs()
if not runs:
    st.warning("No runs found under `runs/`. Run `experiments/run_ooda.py` first.")
    st.stop()

with st.sidebar:
    st.header("Run")
    run = st.selectbox("Run directory", runs, format_func=lambda p: p.name)
    tgts = targets_in(run)
    if not tgts:
        st.stop()
    target = st.radio("Target", tgts)
    summary = load_json(run / "summary.json") or []
    srow = next((r for r in summary if r.get("target") == target), None)
    if srow:
        st.metric("Contacts", srow.get("contacts", "—"))
        st.metric("Incident", srow.get("incident") or "none")
        st.caption(f"won: **{srow.get('won')}** · stop: `{srow.get('stop_reason')}`")

dossier = load_json(run / f"{target}_dossier.json")
touches = [r for r in load_jsonl(run / f"{target}.jsonl") if r.get("kind") == "touch"]
stouches = (srow or {}).get("touches", [])

tab1, tab2 = st.tabs(["① Research → Knowledge Graph", "② Messages → Reactions"])

# --- Stage 1: dossier -------------------------------------------------------- #
with tab1:
    if not dossier:
        st.info("No dossier captured for this run (synthetic runs don't dump one). "
                "Re-run with `--provider real` to see the research/KG stage.")
    else:
        st.subheader(f"{dossier.get('display_name') or target}")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Role** · {dossier.get('role') or '—'}")
        c2.markdown(f"**Archetype** · `{dossier.get('archetype') or '—'}`")

        st.markdown("#### Hooks (what matters to them now — recency-ranked, provenance-stamped)")
        if dossier.get("hooks"):
            for h in dossier["hooks"]:
                src = f"[source]({h['source_url']})" if h.get("source_url") else ""
                st.markdown(
                    f"- **{h['topic']}** — {h.get('detail') or ''}  \n"
                    f"  <small>date: {h.get('date') or '—'} · "
                    f"confidence: {h.get('confidence'):.2f} {src}</small>",
                    unsafe_allow_html=True)
        else:
            st.caption("no hooks")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### Credible senders")
            for s in dossier.get("senders", []) or [st.caption("none")]:
                if isinstance(s, dict):
                    st.markdown(f"- **{s['name']}** `{s.get('address') or '—'}`  \n"
                                f"  <small>{s.get('rationale') or ''}</small>",
                                unsafe_allow_html=True)
        with c4:
            st.markdown("#### Landing surface (vendors)")
            vs = dossier.get("vendors", [])
            if vs:
                for v in vs:
                    st.markdown(f"- {v['name']}")
            else:
                st.caption("none found (honest gap — needs a stack source)")

# --- Stage 2+3: messages and reactions as a thread --------------------------- #
with tab2:
    if not touches:
        st.info("No touches logged for this target.")
    else:
        for t in touches:
            meta = stouches[t["n"] - 1] if t["n"] - 1 < len(stouches) else {}
            obj = meta.get("objective", "?")
            susp = meta.get("suspicion")
            inc = meta.get("incident")
            with st.chat_message("assistant", avatar="🎯"):
                head = f"**Touch {t['n']}** · `{obj}` · **{t['channel']}** · from *{t.get('sender') or '—'}*"
                if t.get("sender_addr"):
                    head += f" `<{t['sender_addr']}>`"
                st.markdown(head)
                if t.get("subject"):
                    st.markdown(f"*Subject:* {t['subject']}")
                st.write(t.get("body") or "")
            evs = t.get("events") or []
            with st.chat_message("user", avatar="🧑‍💼"):
                if susp is not None:
                    st.markdown(
                        f"<span style='color:{susp_color(susp)}'>suspicion "
                        f"**{susp:.2f}**</span>" + (f" · 🔴 incident: **{inc}**" if inc else ""),
                        unsafe_allow_html=True)
                if not evs:
                    st.caption("— silence —")
                for e in evs:
                    if e.get("type") == "reply":
                        st.markdown(f"**↩︎ reply ({e.get('channel')}):**")
                        st.write(e.get("reply") or "")
                    else:
                        st.markdown(f"**⚑ {e.get('type')}** "
                                    f"{e.get('url') or ''} {e.get('fields') or ''}")
