"""Regenerate the JSON Schemas in schemas/ from the Pydantic models.

Each file is named after the artefact kind it describes (``tacit.fragment`` is
``tacit_fragment.schema.json``), matching the ``schema`` URI the artefact carries;
``tacit_context`` describes the conditions and runtime context that several objects embed.

Run: python scripts/generate_schemas.py (also part of `make regen`). A test fails when a
committed schema differs from its model, so the published schemas always match the code.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metis.conditions.context import TacitContext
from metis.consent.model import ConsentRecord
from metis.consent.revocation import RevocationRecord
from metis.fragment.model import TacitFragment
from metis.governance.membership import MembershipRecord
from metis.memory.agent_context import AgentMemoryContext
from metis.memory.tacit import TacitMemoryObject
from metis.models.structured_outputs import ModelAssistRecord
from metis.retrieval.decision import RetrievalDecision
from metis.retrieval.escalation import EscalationDecision
from metis.validation.events import ValidationEvent
from metis.validation.promotion import PromotionRecord
from metis.validation.tier2 import MissionGroupReview

BASE = "https://metis.dev/schemas/0.1"
SCHEMAS = {
    "tacit_agent_memory_context": AgentMemoryContext,
    "tacit_consent_record": ConsentRecord,
    "tacit_escalation_decision": EscalationDecision,
    "tacit_context": TacitContext,
    "tacit_fragment": TacitFragment,
    "tacit_membership_record": MembershipRecord,
    "tacit_memory_object": TacitMemoryObject,
    "tacit_model_assist_record": ModelAssistRecord,
    "tacit_promotion_record": PromotionRecord,
    "tacit_retrieval_decision": RetrievalDecision,
    "tacit_review_decision": MissionGroupReview,
    "tacit_revocation_record": RevocationRecord,
    "tacit_validation_event": ValidationEvent,
}


def schema_for(name: str) -> dict:
    schema = SCHEMAS[name].model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"{BASE}/{name}.schema.json"
    return schema


def render(name: str) -> str:
    return json.dumps(schema_for(name), indent=2) + "\n"


if __name__ == "__main__":
    out = ROOT / "schemas"
    for name in SCHEMAS:
        (out / f"{name}.schema.json").write_text(render(name))
    print(f"wrote {len(SCHEMAS)} schemas to {out}")
