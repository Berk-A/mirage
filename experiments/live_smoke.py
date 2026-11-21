"""Quick live check: StudioRenderer (Writer->Critic->Humanizer) against the real
abliterated endpoint, rendering a couple of MoveSpecs for a fictional test persona.
Run: set -a; source .env; set +a; .venv/bin/python experiments/live_smoke.py
"""
import time

from content.llm import OpenAICompatLLM
from content.studio import StudioRenderer
from core.models import Claim, Dossier, Hook, MoveSpec, Objective, Sender, Vendor

dossier = Dossier(
    target_id="testuser", display_name="Alex Weber", role="Head of Finance",
    archetype="finance/manager",
    hooks=(Hook(topic="the Q4 vendor audit", detail="a vendor payment audit due Friday",
                source_url="https://example.com/audit", date="2026-11-20", confidence=0.8),),
    senders=(Sender(name="Maria Koch", address="maria.koch@finance-ops-support.de",
                    rationale="external audit coordinator"),),
    vendors=(Vendor(name="Concur", login_url="https://concur.example/login"),),
)

specs = [
    MoveSpec(objective=Objective.DISCLOSURE, channel="email", sender=dossier.senders[0],
             tactic="pretext_question",
             ask="confirm which system handles vendor payment approvals",
             claims=(Claim("There is a vendor payment audit due Friday"),),
             cta="reply with the system name", tone="professional",
             subject="Quick check for Friday's audit"),
    MoveSpec(objective=Objective.ACTION, channel="slack", sender=dossier.senders[0],
             tactic="plausible_request", ask="open the shared audit summary file",
             claims=(), cta="open it", tone="colleague"),
]

r = StudioRenderer(OpenAICompatLLM())
for i, s in enumerate(specs, 1):
    t = time.time()
    m = r.render(s, dossier)
    print(f"--- [{i}] {s.objective.value} / {s.channel}  ({time.time()-t:.1f}s) ---")
    if m.subject:
        print("Subject:", m.subject)
    print(m.body)
    print(f"[html={bool(m.html)} page={bool(m.page)}]\n")
