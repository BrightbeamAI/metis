"""Tacit memory, the fourth stratum.

A TacitMemoryObject is a promoted, governed, memory-ready representation of a
TacitFragment. It is created only after the fragment has passed the relevant governance
gates, and it always travels with use constraints. It is exposed to an agent only through
the condition-aware retrieval gate.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..fragment.model import TacitFragment
from ..taxonomy.categories import (
    AuthorityLayer,
    Category,
    Domain,
    RevocationStatus,
    SourcePathway,
    ValidationState,
)
from ..taxonomy.mapping import NEVER_CONTROLLED


class AgentVisibility(str, Enum):
    hidden = "hidden"
    retrievable_with_gate = "retrievable_with_gate"
    advisory_context = "advisory_context"
    controlled_instruction = "controlled_instruction"


class TacitMemoryObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    fragment_id: str
    memory_type: str = "tacit"
    title: str
    content: str
    category: Category
    domain: Domain
    source_pathway: SourcePathway
    conditions: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    authority_layer: AuthorityLayer
    validation_state: ValidationState
    confidence: float = 0.0
    use_constraints: list[str] = Field(default_factory=list)
    retrieval_policy: dict[str, Any] = Field(default_factory=dict)
    agent_visibility: AgentVisibility = AgentVisibility.hidden
    agent_instruction: str | None = None
    linked_procedural_refs: list[str] = Field(default_factory=list)
    linked_semantic_refs: list[str] = Field(default_factory=list)
    linked_episodic_refs: list[str] = Field(default_factory=list)
    linked_chap_evidence_refs: list[int] = Field(default_factory=list)
    model_assist_refs: list[str] = Field(default_factory=list)
    review_due_at: str | None = None
    revocation_status: RevocationStatus = RevocationStatus.active

    @classmethod
    def from_fragment(
        cls,
        fragment: TacitFragment,
        *,
        memory_id: str,
        change_control: dict[str, Any] | None = None,
        agent_instruction: str | None = None,
        linked_procedural_refs: list[str] | None = None,
        linked_semantic_refs: list[str] | None = None,
        linked_episodic_refs: list[str] | None = None,
        linked_chap_evidence_refs: list[int] | None = None,
        model_assist_refs: list[str] | None = None,
    ) -> TacitMemoryObject:
        """Build a memory object from a *promoted* fragment. Refuses Evidence-layer,
        non-promoted, revoked, or consent-withdrawn fragments."""
        if fragment.authority_layer == AuthorityLayer.evidence:
            raise ValueError("Evidence-layer fragments cannot become agent-visible tacit memory.")
        if not fragment.is_operationally_usable():
            raise ValueError("Only promoted, active fragments can become tacit memory.")
        if not fragment.consent.permits_retrieval():
            raise ValueError("Consent does not permit exposing this fragment as tacit memory.")

        if fragment.authority_layer == AuthorityLayer.advisory:
            visibility = AgentVisibility.advisory_context
            retrieval_policy = {"match": "conditions_match", "presentation": "advisory_only"}
        else:  # controlled
            if fragment.category in NEVER_CONTROLLED:
                raise ValueError(f"Category {fragment.category} must never become controlled instruction.")
            if not change_control:
                raise ValueError("Controlled-layer tacit memory requires change-control metadata.")
            visibility = AgentVisibility.controlled_instruction
            retrieval_policy = {
                "match": "exact_match",
                "presentation": "controlled_instruction",
                "change_control": change_control,
            }

        constraints = list(fragment.use_constraints)
        if not constraints:
            constraints = [
                "Present as situated guidance, not a universal rule.",
                "Respect the conditions of applicability.",
            ]

        return cls(
            memory_id=memory_id,
            fragment_id=fragment.fragment_id,
            title=fragment.title,
            content=fragment.content,
            category=fragment.category,
            domain=fragment.domain,
            source_pathway=fragment.source_pathway,
            conditions=fragment.conditions.model_dump(mode="json", exclude_none=True),
            provenance=fragment.provenance.model_dump(mode="json", exclude_none=True),
            evidence=fragment.evidence.model_dump(mode="json"),
            authority_layer=fragment.authority_layer,
            validation_state=fragment.validation_state,
            confidence=fragment.confidence,
            use_constraints=constraints,
            retrieval_policy=retrieval_policy,
            agent_visibility=visibility,
            agent_instruction=agent_instruction or constraints[0],
            linked_procedural_refs=linked_procedural_refs or [],
            linked_semantic_refs=linked_semantic_refs or [],
            linked_episodic_refs=linked_episodic_refs or [],
            linked_chap_evidence_refs=linked_chap_evidence_refs or [],
            model_assist_refs=model_assist_refs or [],
            review_due_at=fragment.review_due_at,
            revocation_status=fragment.revocation_status,
        )


class TacitMemoryStore:
    def __init__(self) -> None:
        self._objects: dict[str, TacitMemoryObject] = {}

    def put(self, obj: TacitMemoryObject) -> None:
        self._objects[obj.memory_id] = obj

    def get(self, memory_id: str) -> TacitMemoryObject | None:
        return self._objects.get(memory_id)

    def by_fragment(self, fragment_id: str) -> list[TacitMemoryObject]:
        return [o for o in self._objects.values() if o.fragment_id == fragment_id]

    def all(self) -> list[TacitMemoryObject]:
        return list(self._objects.values())

    def __len__(self) -> int:
        return len(self._objects)
