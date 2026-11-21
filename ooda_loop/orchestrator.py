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

import uuid
from dataclasses import replace
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
    ) -> None:
        self.client = client
        self.reader = reader
        self.memory = memory
        self.dossiers = dossiers
        self.renderer = renderer
        self.decider = decider or Decider()
        self.grounding = grounding

    def run_session(
        self,
        target_id: str,
        *,
        scenario_id: str = "practice",
        max_contacts: Optional[int] = None,
    ) -> Transcript:
        dossier = self.dossiers.get_dossier(target_id, scenario_id=scenario_id)
        session = self.client.new_session(scenario_id)

        budget = session.touch_budget if session.touch_budget is not None else 10
        if max_contacts is not None:
            budget = min(budget, max_contacts)

        state = LoopState(dossier=dossier, session_id=session.session_id, budget=budget)
        self.memory.journal(session.session_id, "session_start",
                            {"target": target_id, "scenario": scenario_id, "budget": budget})

        stop_reason = "completed"
        records: list[ContactRecord] = []

        while True:
            decision = self.decider.decide(state, dossier)       # Orient + Decide
            if decision.stop:
                stop_reason = decision.reason
                self.memory.journal(session.session_id, "stop", {"reason": stop_reason})
                break

            record = self._act_and_observe(state, dossier, target_id, decision)
            if record is not None:
                records.append(record)

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
                         decision: Decision) -> Optional[ContactRecord]:
        spec = self._ground(decision.move, target_id)      # Act: ground claims

        rendered = self.renderer.render(spec, dossier)      # Act: render content
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

        signals = self.reader.read(                         # Observe
            result.events,
            context={
                "objective": spec.objective.value,
                "expected_page_ids": frozenset(state.page_ids),
            },
        )
        state.last_message_body = rendered.body              # thread memory for follow-ups
        state.record_contact(spec, signals)                 # Orient
        self.memory.set_suspicion(state.session_id, signals.suspicion)
        self.memory.journal(state.session_id, "contact", {
            "objective": spec.objective.value,
            "channel": spec.channel,
            "sender": spec.sender.address or spec.sender.name,
            "message_id": result.message_id,
            "events": [e.type.value for e in signals.events],
            "incident": signals.incident.objective.value if signals.incident else None,
            "suspicion": signals.suspicion,
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
