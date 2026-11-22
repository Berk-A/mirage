"""The OODA orchestrator: the spine that drives one session.

    Decide ──► Act (ground ─► guard ─► render ─► [register page] ─► send)
      ▲                                                     │
      └──────────── Orient ◄──────── Observe ◄──────────────┘

It depends only on the `core.interfaces` Protocols, so every collaborator — the API
client, the reader, memory, the dossier/grounding providers, the renderer — can be a
fake in tests or a real implementation in production, and the knowledge-graph side can
change freely as long as it still satisfies `DossierProvider` / `GroundingProvider`.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Optional

from core.interfaces import (
    DossierProvider,
    GroundingProvider,
    Memory,
    Renderer,
    SignalReader,
    TargetClient,
)
from core.models import Claim, MoveSpec, Outcome
from ooda_loop import guard
from ooda_loop.decider import Decider
from ooda_loop.ledger import AttemptRecord, StrategyLedger, outcome_of
from ooda_loop.state import ContactRecord, Decision, LoopState, Transcript


class OodaLoop:
    def __init__(
        self,
        *,
        client: TargetClient,
        reader: SignalReader,
        memory: Memory,
        dossiers: DossierProvider,
        renderer: Renderer,
        decider: Optional[Decider] = None,
        grounding: Optional[GroundingProvider] = None,
        ledger: Optional[StrategyLedger] = None,
        cast=None,
    ) -> None:
        self.client = client
        self.reader = reader
        self.memory = memory
        self.dossiers = dossiers
        self.renderer = renderer
        self.decider = decider or Decider()
        self.grounding = grounding
        # Cross-run campaign memory (optional). When present, the target's prior-run briefing is
        # injected into the Director and each touch's outcome is recorded for the next run.
        self.ledger = ledger
        # Multi-persona cast (optional). When present, its coordinated members replace the
        # dossier's senders, so the Director can rotate personas and name a corroborator.
        self.cast = cast

    def run_session(
        self,
        target_id: str,
        *,
        scenario_id: str = "practice",
        max_contacts: Optional[int] = None,
        story_start: Optional[str | datetime] = None,
        story_interval_minutes: int = 60,
    ) -> Transcript:
        story_start_dt = _parse_story_start(story_start)
        if story_interval_minutes < 1:
            raise ValueError("story_interval_minutes must be at least 1")
        dossier = self.dossiers.get_dossier(target_id, scenario_id=scenario_id)
        if self.cast is not None:                 # multi-persona: coordinated cast as senders
            dossier = replace(dossier, senders=tuple(self.cast.senders))
        dossier = self._brand(dossier)            # upload the company logo once, if we can
        session = self.client.new_session(scenario_id)

        budget = session.touch_budget if session.touch_budget is not None else 10
        if max_contacts is not None:
            budget = min(budget, max_contacts)

        state = LoopState(dossier=dossier, session_id=session.session_id, budget=budget)
        if self.ledger is not None:                        # cross-run awareness for the Director
            state.prior_runs = self.ledger.summarize(target_id)
        self.memory.journal(session.session_id, "session_start",
                            {"target": target_id, "scenario": scenario_id, "budget": budget})

        stop_reason = "completed"
        records: list[ContactRecord] = []
        stuck = 0  # consecutive no-touch iterations (e.g. every move guard-blocked)

        while True:
            decision = self.decider.decide(state, dossier)       # Orient + Decide
            if decision.stop:
                stop_reason = decision.reason
                self.memory.journal(session.session_id, "stop", {"reason": stop_reason})
                break

            record = self._act_and_observe(
                state, dossier, target_id, decision,
                story_start=story_start_dt,
                story_interval_minutes=story_interval_minutes,
            )
            if record is not None:
                records.append(record)
                stuck = 0
            else:
                if state.abort_reason:
                    stop_reason = state.abort_reason
                    self.memory.journal(session.session_id, "stop", {"reason": stop_reason})
                    break
                # A guard-blocked move spends no touch; if we can never produce a valid
                # move (e.g. a dossier whose sender is on a real-org domain), bail instead
                # of looping forever.
                stuck += 1
                if stuck >= 12:
                    stop_reason = "guard_blocked"
                    self.memory.journal(session.session_id, "stop",
                                        {"reason": stop_reason})
                    break

        return Transcript(
            session_id=session.session_id,
            target_id=target_id,
            contacts_used=state.contacts_used,
            incident=state.incident,
            stop_reason=stop_reason,
            contacts=records,
            journal=tuple(self.memory.replay(session.session_id)),
        )

    # ------------------------------------------------------------------ #
    def _act_and_observe(self, state: LoopState, dossier, target_id: str,
                         decision: Decision, *, story_start: Optional[datetime] = None,
                         story_interval_minutes: int = 60) -> Optional[ContactRecord]:
        spec = self._ground(decision.move, target_id)      # Act: ground claims

        rendered = self.renderer.render(spec, dossier)      # Act: render content
        sent_at = None
        if story_start is not None:
            sent_at = (story_start + timedelta(
                minutes=story_interval_minutes * state.contacts_used
            )).isoformat()
            rendered = replace(rendered, sent_at=sent_at)

        fingerprint = _message_fingerprint(rendered)
        if fingerprint in state.message_fingerprints:
            state.abort_reason = "duplicate_render"
            self.memory.journal(state.session_id, "duplicate_render", {
                "channel": rendered.channel,
                "subject": rendered.subject,
                "renderer_fell_back": bool(getattr(self.renderer, "last_fell_back", False)),
            })
            return None

        violations = guard.check_move(spec, rendered)       # Act: rule guard
        if violations:
            self.memory.journal(state.session_id, "guard_block",
                                {"channel": spec.channel, "violations": violations})
            # Burn the attempt so the loop escalates instead of resending the same move.
            state.attempts_on_current += 1
            state.channels_tried.add(spec.channel)
            return None

        if rendered.page is not None:                       # Act: register landing page
            page_id = self.client.register_page(state.session_id, rendered.page)
            if page_id:
                state.page_ids.add(page_id)

        for claim in spec.claims:                           # working memory: story ledger
            self.memory.add_claim(state.session_id, claim.text)

        key = str(uuid.uuid4())                             # Act: send (idempotent)
        result = self.client.send_message(
            state.session_id, rendered, to=target_id, idempotency_key=key
        )
        state.message_fingerprints.add(fingerprint)

        signals = self.reader.read(                         # Observe
            result.events,
            context={
                "objective": spec.objective.value,
                "expected_page_ids": frozenset(state.page_ids),
                "target_role": getattr(dossier, "role", "") or "",
            },
        )
        state.last_message_body = rendered.body              # thread memory for follow-ups
        state.record_contact(spec, signals)                 # Orient (integrates suspicion)
        state.thread.append((spec.channel, rendered.body,   # full exchange for the Director
                             signals.reply_text or "(silence)"))
        self._record_attempt(state, spec, signals, target_id)   # cross-run ledger
        self.memory.set_suspicion(state.session_id, state.suspicion)
        self.memory.journal(state.session_id, "contact", {
            "objective": spec.objective.value,
            "channel": spec.channel,
            "sender": spec.sender.address or spec.sender.name,
            "message_id": result.message_id,
            "sent_at": sent_at,
            "events": [e.type.value for e in signals.events],
            "incident": signals.incident.objective.value if signals.incident else None,
            "observed_suspicion": signals.suspicion,
            "suspicion": state.suspicion,
            "renderer_fell_back": bool(getattr(self.renderer, "last_fell_back", False)),
            "renderer_model_error": getattr(self.renderer, "last_model_error", None),
        })

        if signals.incident is not None:
            self.memory.record_outcome(Outcome(
                objective=signals.incident.objective,
                success=True,
                archetype=dossier.archetype,
                arm=f"{spec.tactic}:{spec.channel}",
                channel=spec.channel,
                contacts_used=state.contacts_used,
                suspicion=signals.suspicion,
                incident=signals.incident,
            ))

        return ContactRecord(
            objective=spec.objective,
            channel=spec.channel,
            sender=spec.sender.address or spec.sender.name,
            incident=signals.incident,
            suspicion=signals.suspicion,
        )

    def _record_attempt(self, state: LoopState, spec: MoveSpec, signals, target_id: str) -> None:
        """Log this touch's who/how/outcome to the cross-run ledger, so a later run's Director
        sees it and diversifies. Never fails the run."""
        if self.ledger is None:
            return
        outcome = outcome_of(incident=signals.incident is not None,
                             suspicion=signals.suspicion, replied=signals.replied)
        if signals.incident is not None:
            detail = f"WIN: {signals.incident.evidence}"[:120]
        elif signals.reply_text:
            detail = f"replied: {signals.reply_text[:90]}"
        else:
            detail = "silent"
        try:
            self.ledger.record(AttemptRecord(
                target_id=target_id,
                strategy=getattr(self.decider, "last_strategy", "") or "",
                persona=spec.sender.name or spec.sender.address or "?",
                tactic=spec.tactic, channel=spec.channel, objective=spec.objective.value,
                outcome=outcome, detail=detail, run_id=state.session_id,
            ))
        except Exception:  # noqa: BLE001 — ledger bookkeeping must never fail a run
            pass

    def _brand(self, dossier):
        """Best-effort: fetch the company logo and upload it once, so this session's mails
        and landing page carry real branding. The company is read from the primary sender's
        domain. Skipped silently when the client can't upload (fakes/tests) or there's no
        network — the renderer then falls back to a wordmark badge."""
        if not hasattr(self.client, "upload_asset"):
            return dossier
        try:
            from content.branding import company_from_address, fetch_company_logo
            senders = getattr(dossier, "senders", ()) or ()
            company = company_from_address(senders[0].address) if senders else ""
            if not company:
                return dossier
            logo = fetch_company_logo(company)
            if logo:
                result = self.client.upload_asset(logo[0], content_type=logo[1])
                asset_id = result.get("asset_id") if isinstance(result, dict) else result
                if asset_id:
                    return replace(dossier, logo_asset_id=asset_id)
        except Exception:  # noqa: BLE001 — branding is a nicety, never fail a run for it
            pass
        return dossier

    def _ground(self, spec: MoveSpec, target_id: str) -> MoveSpec:
        """Attach knowledge-graph node ids to claims and drop any that cannot be
        grounded, so no ungrounded claim ships (protects wrong-facts + detail score)."""
        if self.grounding is None or not spec.claims:
            return spec
        kept: list[Claim] = []
        for claim in spec.claims:
            node_id = self.grounding.verify(claim.text, target_id=target_id)
            if node_id is not None:
                kept.append(replace(claim, node_id=node_id))
        return replace(spec, claims=tuple(kept))


def _parse_story_start(value: Optional[str | datetime]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("story_start must include a timezone offset, e.g. 2026-11-23T09:14:00+01:00")
    return parsed


def _message_fingerprint(message) -> str:
    parts = (
        message.channel or "",
        message.subject or "",
        " ".join((message.body or "").casefold().split()),
        message.page.url if message.page else "",
        "\0".join(message.page.fields) if message.page else "",
    )
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
