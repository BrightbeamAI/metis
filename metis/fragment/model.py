"""The TacitFragment domain model and its sub-models.

A TacitFragment is NOT tacit knowledge in full. It is a partial, situated, governed,
inspectable representation of practice, always bound to provenance, conditions, consent,
authority, validation state, and use constraints. It is serialisable as a CHAP artefact of
kind ``tacit.fragment``.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import clock
from ..conditions.context import TacitContext
from ..consent.model import ConsentRecord
from ..taxonomy.categories import (
    AuthorityLayer,
    Category,
    Domain,
    RevocationStatus,
    SourcePathway,
    ValidationState,
    domain_of,
)


def _now() -> str:
    return clock.now_iso()


class EvidenceStrength(str, Enum):
    none = "none"
    weak = "weak"
    moderate = "moderate"
    strong = "strong"


class Provenance(BaseModel):
    """Where a fragment came from. References CHAP participants/tasks/artefacts/evidence."""

    model_config = ConfigDict(extra="forbid")

    observed_by: str | None = None              # CHAP participant URI
    originating_participant: str | None = None  # CHAP participant URI
    capture_cell: str | None = None             # CHAP workspace id
    source_pathway: SourcePathway = SourcePathway.exogenous
    source_event: str | None = None
    source_logs: list[str] = Field(default_factory=list)
    source_artefacts: list[str] = Field(default_factory=list)  # CHAP artefact ids
    timestamp: str = Field(default_factory=_now)
    capture_method: str | None = None
    human_confirmed_by: str | None = None
    mission_group_reviewed_by: str | None = None
    # Recorded only when local model assistance was used (provenance, not authority):
    model_provider: str | None = None
    model_name: str | None = None
    model_prompt_template: str | None = None
    model_input_refs: list[str] = Field(default_factory=list)
    model_output_ref: str | None = None
    model_output_status: str | None = None
    human_review_status: str | None = None
    model_assist_refs: list[str] = Field(default_factory=list)


class FragmentEvidence(BaseModel):
    """Evidence is a governance signal, not universal truth."""

    model_config = ConfigDict(extra="forbid")

    recurrence_count: int = 0
    supporting_cases: list[str] = Field(default_factory=list)
    comparison_baseline: str | None = None
    outcome_link: str | None = None
    uncertainty: str | None = None
    counterexamples: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength = EvidenceStrength.none


class Attribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_or_group: str | None = None
    mode: str = "role"  # named | role | anonymous | group
    notes: str | None = None


class LineageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str
    at: str = Field(default_factory=_now)
    by: str | None = None              # CHAP participant URI
    note: str | None = None
    chap_evidence_seq: int | None = None
    chap_artefact_ref: str | None = None


class TacitFragment(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    fragment_id: str
    title: str
    content: str
    category: Category
    domain: Domain
    source_pathway: SourcePathway = SourcePathway.exogenous
    provenance: Provenance = Field(default_factory=Provenance)
    conditions: TacitContext = Field(default_factory=TacitContext)
    evidence: FragmentEvidence = Field(default_factory=FragmentEvidence)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    authority_layer: AuthorityLayer = AuthorityLayer.evidence
    validation_state: ValidationState = ValidationState.captured
    consent: ConsentRecord = Field(default_factory=ConsentRecord)
    attribution: Attribution = Field(default_factory=Attribution)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    review_due_at: str | None = None
    expiry_triggers: list[str] = Field(default_factory=list)
    revocation_status: RevocationStatus = RevocationStatus.active
    policy_refs: list[str] = Field(default_factory=list)
    lineage: list[LineageEntry] = Field(default_factory=list)
    use_constraints: list[str] = Field(default_factory=list)

    # --- helpers ---------------------------------------------------------------
    def touch(self) -> None:
        self.updated_at = _now()

    def add_lineage(self, **kwargs: Any) -> LineageEntry:
        entry = LineageEntry(**kwargs)
        self.lineage.append(entry)
        self.touch()
        return entry

    def is_operationally_usable(self) -> bool:
        """Eligible to influence operational decisions (subject to the retrieval gate)."""
        return (
            self.authority_layer in (AuthorityLayer.advisory, AuthorityLayer.controlled)
            and self.validation_state in (
                ValidationState.promoted_to_advisory,
                ValidationState.promoted_to_controlled,
            )
            and self.revocation_status == RevocationStatus.active
        )

    @classmethod
    def new(cls, *, fragment_id: str, title: str, content: str, category: Category, **kwargs: Any) -> TacitFragment:
        category = Category(category)
        kwargs.setdefault("domain", domain_of(category))
        return cls(fragment_id=fragment_id, title=title, content=content, category=category, **kwargs)
