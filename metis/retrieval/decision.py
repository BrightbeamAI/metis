"""The tacit.retrieval_decision artefact content."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import clock


class BlockedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    memory_id: str | None = None
    reason: str
    detail: str | None = None


class EligibleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    memory_id: str | None = None
    authority_layer: str
    confidence: float = 0.0
    use_constraints: list[str] = Field(default_factory=list)


class RetrievalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_type: str = "tacit.retrieve"
    policy_id: str = "metis/retrieval/1.0"
    requested_role: str | None = None
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    hints_observed: dict[str, Any] = Field(default_factory=dict)
    eligible: list[EligibleItem] = Field(default_factory=list)
    blocked: list[BlockedItem] = Field(default_factory=list)
    rationale: str = ""
    decided_at: str = Field(default_factory=clock.now_iso)
