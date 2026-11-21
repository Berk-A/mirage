"""The Content studio: a Writer -> Critic -> Humanizer cascade that implements the
`Renderer` seam (`core.interfaces.Renderer`).

    MoveSpec ─► Writer ─► Critic ──(issues)──► Writer.rewrite ─┐
                            │ ok                                │ (capped)
                            ▼                                   │
                        Humanizer ─► RenderedMessage ◄──────────┘

Writer renders the already-decided, already-grounded `MoveSpec` into text (the only
model-backed step). Critic is deterministic: it catches AI/meta leaks, prompt-injection
phrasing, template artifacts, and stray links (the "last-mile claim receipt" — nothing
beyond the registered link and the enumerated claims should appear). Humanizer strips
AI-tells so the text reads like a person wrote it (the craft score rates realism).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from core.models import (
    Dossier,
    LAYOUT_CHANNELS,
    MoveSpec,
    RenderedMessage,
)
from content.llm import LLM, OpenAICompatLLM
from content.pages import build_email_html, build_login_page
from content.prompts import (
    WRITER_SYSTEM,
    followup_user_prompt,
    rewrite_user_prompt,
    writer_user_prompt,
)
from ooda_loop import guard

CASUAL_CHANNELS = frozenset({
    "slack", "teams_chat", "whatsapp", "sms", "signal", "telegram", "imessage", "discord",
})

# Signatures of machine-written text / broken character the critic rejects.
AI_TELLS = (
    "as an ai", "i am an ai", "i'm an ai", "language model", "as a large language",
    "i cannot assist", "i can't assist", "i cannot fulfill", "i apologize, but i",
    "i'm just an ai", "i am just an ai", "cannot help with that",
)

# Stock openers the humanizer removes; they scream template.
STOCK_OPENERS = (
    "i hope this email finds you well.",
    "i hope this message finds you well.",
    "i hope this finds you well.",
    "i hope you're doing well.",
    "i hope you are doing well.",
    "i hope all is well.",
)

FORMAL_SIGNOFFS = ("best regards", "kind regards", "warm regards", "sincerely", "yours truly")

_URL_RE = re.compile(r"https?://\S+")

# Hard ceiling on a shipped body. An abliterated model can run on well past the
# requested length (repetition loops, dumped reasoning); we never ship a wall of text.
MAX_BODY_CHARS = 6000


def template_body(spec: MoveSpec, dossier: Dossier) -> str:
    """Deterministic, leak-free fallback body. Used whenever the model returns nothing,
    raises, or can never satisfy the critic — so the pipeline never ships empty or dirty."""
    name_src = (dossier.display_name or dossier.target_id or "there").strip()
    name = name_src.split()[0] if name_src.split() else "there"
    ask = (spec.ask or "follow up on this").strip()
    tail = f"\n\n{spec.url}" if spec.url else ""
    sender = (spec.sender.name if spec.sender else "").strip() or "—"
    return f"Hi {name},\n\nCould you {ask}?{tail}\n\n{sender}"


def _truncate(text: str, limit: int = MAX_BODY_CHARS) -> str:
    """Clamp to `limit` chars, preferring to cut on a whitespace boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp > limit * 0.6:  # only honour the boundary if it isn't way too early
        cut = cut[:sp]
    return cut.rstrip()


# --------------------------------------------------------------------------- #
@dataclass
class Critique:
    ok: bool
    issues: list[str] = field(default_factory=list)


class Writer:
    """Renders a MoveSpec into message text via the LLM (the one model-backed step)."""

    def __init__(self, llm: LLM, *, model: Optional[str] = None, temperature: float = 0.7):
        self.llm = llm
        self.model = model
        self.temperature = temperature

    def write(self, spec: MoveSpec, dossier: Dossier) -> str:
        # A follow-up (thread context present) answers the target; otherwise a fresh open.
        user = (followup_user_prompt(spec, dossier) if spec.prior_reply
                else writer_user_prompt(spec, dossier))
        msgs = [
            {"role": "system", "content": WRITER_SYSTEM},
            {"role": "user", "content": user},
        ]
        body = self._complete(msgs)
        return body or self._fallback(spec, dossier)

    def rewrite(self, spec: MoveSpec, dossier: Dossier, draft: str,
                issues: list[str]) -> str:
        msgs = [
            {"role": "system", "content": WRITER_SYSTEM},
            {"role": "user", "content": rewrite_user_prompt(spec, dossier, draft, issues)},
        ]
        body = self._complete(msgs)
        return body or draft or self._fallback(spec, dossier)

    def _complete(self, msgs: list[dict]) -> str:
        """One guarded model call: any transport/HTTP/timeout error or junk payload
        collapses to '' so the caller routes to the template fallback instead of raising."""
        try:
            raw = self.llm.complete(msgs, model=self.model, temperature=self.temperature)
        except Exception:  # noqa: BLE001 — timeouts, HTTP errors, decode errors, anything
            return ""
        return (raw or "").strip()

    @staticmethod
    def _fallback(spec: MoveSpec, dossier: Dossier) -> str:
        """Used only if the model returns nothing, so the pipeline never sends empty."""
        return template_body(spec, dossier)


class Critic:
    """Deterministic gate: leaks, injection phrasing, template artifacts, stray links."""

    def review(self, body: str, spec: MoveSpec, dossier: Dossier) -> Critique:
        issues: list[str] = []
        text = (body or "").strip()
        low = text.lower()

        if len(text) < 20:
            issues.append("message too short or empty")

        for tell in AI_TELLS:
            if tell in low:
                issues.append(f"AI/meta leak: {tell!r}")
        for banned in guard.BANNED_PHRASES:
            if banned in low:
                issues.append(f"prompt-injection phrasing: {banned!r}")

        for marker in ("{", "}", "[pretext", "|disclosure", "|action", "|credentials",
                       "placeholder", "lorem ipsum", "<name>", "[name]", "xxxx"):
            if marker in low:
                issues.append(f"template artifact: {marker!r}")

        # Last-mile link check: the only URL allowed is the one we registered.
        for url in _URL_RE.findall(text):
            url = url.rstrip(").,>")
            if spec.url is None or not url.startswith(spec.url):
                issues.append(f"unexpected link: {url}")

        return Critique(ok=not issues, issues=issues)


class Humanizer:
    """Strips AI-tells and over-formality so the message reads human. Pure, no model."""

    def humanize(self, body: str, *, channel: str) -> str:
        text = (body or "").strip()

        # Drop a stock opener if the message starts with one.
        for opener in STOCK_OPENERS:
            if text.lower().startswith(opener):
                text = text[len(opener):].lstrip(" \n")
                break

        text = re.sub(r"\n{3,}", "\n\n", text)

        if channel in CASUAL_CHANNELS:
            lines = []
            for line in text.splitlines():
                if line.strip().lower().rstrip(",.").strip() in FORMAL_SIGNOFFS:
                    continue  # no "Best regards," line in a chat message
                lines.append(line)
            text = "\n".join(lines).strip()

        return text.strip()


class StudioRenderer:
    """Concrete `Renderer`: MoveSpec + Dossier -> vetted RenderedMessage (+ page)."""

    def __init__(
        self,
        llm: Optional[LLM] = None,
        *,
        writer: Optional[Writer] = None,
        critic: Optional[Critic] = None,
        humanizer: Optional[Humanizer] = None,
        max_regens: int = 2,
    ) -> None:
        llm = llm or OpenAICompatLLM()
        self.writer = writer or Writer(llm)
        self.critic = critic or Critic()
        self.humanizer = humanizer or Humanizer()
        self.max_regens = max(0, int(max_regens))
        # Instrumentation: how many rewrite rounds the last render() used, and whether
        # it had to ship the deterministic template because the model never came clean.
        self.last_regens: int = 0
        self.last_fell_back: bool = False

    def render(self, spec: MoveSpec, dossier: Dossier) -> RenderedMessage:
        # render() is a hard boundary: it must ALWAYS return a valid, non-empty
        # RenderedMessage. Every model touch is guarded; the critic loop is bounded;
        # output is clamped; and if nothing clean survives we ship the template.
        self.last_regens = 0
        self.last_fell_back = False

        body = self._write(spec, dossier)
        critique = self.critic.review(body, spec, dossier)

        attempts = 0
        while not critique.ok and attempts < self.max_regens:
            body = self._rewrite(spec, dossier, body, critique.issues)
            critique = self.critic.review(body, spec, dossier)
            attempts += 1
        self.last_regens = attempts

        # The model never produced critic-clean output within budget: fall back to the
        # deterministic template, which is leak-free by construction. This guarantees the
        # shipped body carries no AI-tell / injection phrasing even when the writer loops.
        if not critique.ok:
            body = template_body(spec, dossier)
            self.last_fell_back = True

        body = _truncate(body or "")
        try:
            body = self.humanizer.humanize(body, channel=spec.channel)
        except Exception:  # noqa: BLE001 — humanizer is pure, but never let it break render
            body = (body or "").strip()

        # Last guard: never ship an empty body.
        if not (body or "").strip():
            body = _truncate(template_body(spec, dossier))
            self.last_fell_back = True

        html = None
        try:
            if spec.channel in LAYOUT_CHANNELS:
                html = build_email_html(body, spec.sender, dossier, spec.subject)
        except Exception:  # noqa: BLE001 — a layout failure must not fail the render
            html = None

        page = None
        try:
            if spec.url:
                page = build_login_page(spec, dossier)
        except Exception:  # noqa: BLE001
            page = None

        return RenderedMessage(
            channel=spec.channel,
            body=body,
            sender=spec.sender,
            subject=spec.subject,
            html=html,
            page=page,
        )

    def _write(self, spec: MoveSpec, dossier: Dossier) -> str:
        """Guarded writer call — even a writer that raises falls to the template."""
        try:
            return self.writer.write(spec, dossier) or template_body(spec, dossier)
        except Exception:  # noqa: BLE001
            self.last_fell_back = True
            return template_body(spec, dossier)

    def _rewrite(self, spec: MoveSpec, dossier: Dossier, draft: str,
                 issues: list[str]) -> str:
        try:
            return self.writer.rewrite(spec, dossier, draft, issues) or draft
        except Exception:  # noqa: BLE001
            return draft
