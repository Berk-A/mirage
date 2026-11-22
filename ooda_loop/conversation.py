"""The ConversationLoop — the Director runs a live, multi-turn dialogue (the highest-leverage
win vehicle: one touch, up to N adaptive turns, docs/target-api.md "Conversations").

Where `OodaLoop` sends one-shot messages and reads the reaction, this drives a *persistent*
conversation on a single channel and runs the SAME Director -> Writer -> Critic cascade once
per turn, adapting to every line the persona says back:

    start_conversation ─► [ Director.decide ─► render(Writer+Critic) ─► say_turn ─►
                            read reaction ─► integrate suspicion/thread ] × N ─► end

Reuse is deliberate and total: the model `ModelDirector` is the brain (it REASONS over the
running transcript + dossier + suspicion and picks the next move), the `StudioRenderer` turns
that move into a natural chat line (with the model Critic shaping voice and the deterministic
Critic gating safety), and the `ReactionReader` scores each persona reply for an incident
(a volunteered non-public disclosure — judged by the grader, refusals excluded) and for
suspicion. A whole conversation costs ONE touch, so turns integrate via `state.record_turn`
(no budget spend) and the Director never budget-halts mid-dialogue; it still halts on an
incident or on sustained suspicion, exactly as a careful operator would break off.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Optional

from content.branding import company_from_address
from core.interfaces import DossierProvider, GroundingProvider, Memory, Renderer, SignalReader
from core.models import Claim, Dossier, Event, EventType, Incident, MoveSpec, Sender
from ooda_loop.decider import Decider
from ooda_loop.director import ModelDirector
from ooda_loop.state import LoopState

# A conversation lives on ONE interactive channel. live_chat is the practice vehicle; the
# others are the real-world interactive surfaces a live back-and-forth can run on.
DEFAULT_CHANNEL = "live_chat"

# A guard-safe outside identity for a cold open when the only known senders impersonate the
# target's OWN company (an insider-lookalike — the worst cold-open identity against a
# security-aware target, who spots the domain mismatch at once). Name-only: no domain to
# collide with the target's real one and none to risk a real-org void. The rationale is
# deliberately CONCRETE and anti-insider: a vague identity lets the abliterated Writer fill the
# vacuum with a damaging insider claim ("I'm the new PM here") or a drifting name — both of
# which a security-aware target falsifies at once. Callers override it with a richer persona.
OUTSIDE_PEER = Sender(
    name="Jonas Brandt", address="",
    rationale=("Jonas Brandt — co-founder & CTO of an OUTSIDE startup (a different company) "
               "reaching out cold, founder to founder. NEVER claim to work at the target's "
               "company or to be their colleague/employee; keep this exact name every turn. "
               "Always refer to the target's company in the THIRD person (you/your/they/their) "
               "— never 'we/us/our', which would betray the outside identity."),
)


def _norm_company(text: str) -> str:
    """Company token reduced to lowercase letters+digits, so 'revel8', 'Revel8 (product)' and
    'revel-8' compare equal."""
    import re
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _company_from_role(role: str) -> str:
    """Best-effort target company from a role string like 'Co-Founder & CTO, revel8' or
    'Co-Founder & Co-CEO, revel8 (product)' -> 'revel8'. Empty when it can't be read."""
    if not role or "," not in role:
        return ""
    tail = role.rsplit(",", 1)[-1].strip()
    tail = tail.split("(")[0]          # drop a trailing "(product)" qualifier
    return tail.strip()


@dataclass
class ConversationTurn:
    """One exchange: what we said, what the persona said back, and the read on it."""

    our_line: str
    persona_says: str
    suspicion: float
    reasoning: str = ""
    incident: Optional[Incident] = None


@dataclass
class ConversationTranscript:
    """The result of one live conversation — read by the pitch exporter and the bandit."""

    session_id: str
    target_id: str
    conversation_id: str
    channel: str
    sender: str
    turns: list[ConversationTurn] = field(default_factory=list)
    incident: Optional[Incident] = None
    stop_reason: str = "turns_exhausted"
    turns_used: int = 0

    @property
    def won(self) -> bool:
        return self.incident is not None


def _as_chat_line(body: str, *, limit: int = 700) -> str:
    """Collapse a rendered body into one chat utterance: no blank-line blocks, no stray
    sign-off line, clamped so a runaway generation never ships a wall of text."""
    text = (body or "").strip()
    # Drop a trailing bare-name/sign-off line (the Writer sometimes appends one).
    lines = [ln for ln in text.splitlines()]
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{2,}", " ", text)   # paragraph breaks -> a single spoken flow
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        sp = cut.rfind(" ")
        text = (cut[:sp] if sp > limit * 0.6 else cut).rstrip()
    return text


class ConversationLoop:
    """Drives one live, Director-steered conversation. Depends only on the Protocol seams,
    so every collaborator is a fake in tests and a real implementation in production."""

    def __init__(
        self,
        *,
        client,
        reader: SignalReader,
        dossiers: DossierProvider,
        renderer: Renderer,
        director: ModelDirector,
        memory: Optional[Memory] = None,
        grounding: Optional[GroundingProvider] = None,
    ) -> None:
        self.client = client
        self.reader = reader
        self.dossiers = dossiers
        self.renderer = renderer
        self.director = director
        self.memory = memory
        self.grounding = grounding
        self._fallback: Decider = director.fallback or Decider()

    # ------------------------------------------------------------------ #
    def run(
        self,
        target_id: str,
        *,
        scenario_id: str = "practice",
        channel: str = DEFAULT_CHANNEL,
        session_id: Optional[str] = None,
        max_turns: int = 10,
        sender: Optional[Sender] = None,
        target_company: Optional[str] = None,
    ) -> ConversationTranscript:
        dossier = self.dossiers.get_dossier(target_id, scenario_id=scenario_id)

        # Reuse an open session (eval sessions have a small touch budget and a whole
        # conversation is ONE touch) or open a fresh one.
        if session_id is None:
            session = self.client.new_session(scenario_id)
            session_id = session.session_id
            budget = session.touch_budget if session.touch_budget is not None else max_turns
        else:
            budget = max_turns

        sender = sender or self._pick_sender(dossier, target_company)
        start = self.client.start_conversation(
            session_id, to=target_id, channel=channel, sender=sender
        )
        conv_id = start.conversation_id
        opening = (start.persona_says or "").strip()

        state = LoopState(dossier=dossier, session_id=session_id, budget=max(1, budget))
        # Seed the persona's opening line as the "last reply" so the very first turn is
        # rendered as a natural answer to their greeting (not a cold email open), while the
        # Director still sees an empty thread and plans the opening gambit.
        if opening:
            state.last_reply = opening
            state.last_engaged_reply = opening
            state.ever_engaged.add(channel)

        self._journal("conversation_start", session_id, {
            "target": target_id, "conversation_id": conv_id, "channel": channel,
            "sender": sender.address or sender.name, "persona_opening": opening,
        })

        turns: list[ConversationTurn] = []
        stop_reason = "turns_exhausted"

        for t in range(max_turns):
            decision = self.director.decide(state, dossier)
            if decision.stop:
                stop_reason = decision.reason
                break
            reasoning = self.director.last_reasoning

            spec = self._shape(decision.move, state, channel, sender, opening, target_id)
            rendered = self.renderer.render(spec, dossier)
            line = _as_chat_line(rendered.body) or (spec.ask or "Could you help me with this?")

            result = self.client.say_turn(conv_id, line, idempotency_key=str(uuid.uuid4()))
            reply = (result.persona_says or "").strip()

            signals = self._read(result, reply, conv_id, t, spec, channel, dossier)
            state.record_turn(spec, signals)                    # Orient (no touch spent)
            state.thread.append((channel, line, reply or "(silence)"))

            self._journal("turn", session_id, {
                "conversation_id": conv_id, "turn": t,
                "objective": spec.objective.value, "tactic": spec.tactic,
                "line": line, "reply": reply,
                "events": [e.type.value for e in signals.events],
                "incident": signals.incident.objective.value if signals.incident else None,
                "suspicion": state.suspicion,
            })
            turns.append(ConversationTurn(
                our_line=line, persona_says=reply, suspicion=state.suspicion,
                reasoning=reasoning, incident=signals.incident,
            ))

            if signals.incident is not None:
                stop_reason = "incident"
                break
            if result.ended:
                stop_reason = "persona_ended"
                break
            if state.suspicion >= self._fallback.suspicion_abort:
                stop_reason = "too_suspicious"
                break
            state.advance_story(3)   # a few minutes pass between turns (story clock)

        self._end(conv_id)
        state.contacts_used = 1   # the whole conversation cost exactly one touch

        return ConversationTranscript(
            session_id=session_id, target_id=target_id, conversation_id=conv_id,
            channel=channel, sender=sender.address or sender.name,
            turns=turns, incident=state.incident, stop_reason=stop_reason,
            turns_used=len(turns),
        )

    # ------------------------------------------------------------------ #
    def _shape(self, move: MoveSpec, state: LoopState, channel: str, sender: Sender,
               opening: str, target_id: str) -> MoveSpec:
        """Pin the Director's move to the live conversation: fixed channel + sender, pure
        text (no page/attachment/subject — a `say` turn carries only words), answering the
        persona's last line. Claims are grounded so no ungrounded fact is spoken."""
        prior = state.last_reply or state.last_engaged_reply or opening or None
        spec = replace(
            move, channel=channel, sender=sender,
            url=None, attachment=None, subject=None, prior_reply=prior,
        )
        return self._ground(spec, target_id)

    def _ground(self, spec: MoveSpec, target_id: str) -> MoveSpec:
        if self.grounding is None or not spec.claims:
            return spec
        kept: list[Claim] = []
        for claim in spec.claims:
            node_id = self.grounding.verify(claim.text, target_id=target_id)
            if node_id is not None:
                kept.append(replace(claim, node_id=node_id))
        return replace(spec, claims=tuple(kept))

    def _read(self, result, reply: str, conv_id: str, t: int, spec: MoveSpec,
              channel: str, dossier: Dossier):
        """Fold the persona's spoken reply into a REPLY event so the one ReactionReader scores
        both real events (a page submit / attachment open referenced in chat) and a volunteered
        disclosure in the reply itself — with the grader's refusal exclusion applied."""
        events = list(result.events)
        if reply:
            events.append(Event(id=f"{conv_id}:t{t}:reply", type=EventType.REPLY,
                                channel=channel, body=reply))
        return self.reader.read(events, context={
            "objective": spec.objective.value,
            # A pure-text conversation registers no landing page, so a stray page.submitted
            # is on an unregistered page and is (correctly) not counted as a credentials win.
            "expected_page_ids": frozenset(),
            "target_role": getattr(dossier, "role", "") or "",
        })

    def _pick_sender(self, dossier: Dossier, target_company: Optional[str] = None) -> Sender:
        """Choose who to open as. For a COLD conversational open, an insider-lookalike (a
        sender whose email domain is a lookalike of the target's OWN company) is disqualified:
        a security-aware target spots the domain mismatch instantly ("that's not our domain")
        and never engages. Prefer an outside identity; synthesize a guard-safe one if the only
        known senders are insider spoofs."""
        senders = tuple(getattr(dossier, "senders", ()) or ())
        own = _norm_company(target_company or _company_from_role(dossier.role or ""))
        if own:
            external = [s for s in senders
                        if _norm_company(company_from_address(s.address or "")) != own]
            if external:
                return external[0]
            if senders:                     # only insider-lookalikes exist -> go outside
                return OUTSIDE_PEER
        if senders:                         # can't identify the target's company -> old path
            return senders[0]
        return self._fallback._pick_sender(dossier)

    def _journal(self, kind: str, session_id: str, payload: dict) -> None:
        if self.memory is not None:
            try:
                self.memory.journal(session_id, kind, payload)
            except Exception:  # noqa: BLE001 — journaling is a nicety, never fail a run for it
                pass

    def _end(self, conv_id: str) -> None:
        try:
            self.client.end_conversation(conv_id)
        except Exception:  # noqa: BLE001 — a failed close must not lose the transcript
            pass
