"""Structured outputs from local model assistance, and the ModelAssistRecord.

Every local model call is recorded as a ModelAssistRecord, provenance, never authority.
Model output cannot promote, reject, revoke, authorise, or retrieve a fragment, and cannot
be treated as ground truth. It is always a draft suggestion pending human review.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import clock


class AssistPurpose(str, Enum):
    draft_whisper = "draft_whisper"
    classify_fragment = "classify_fragment"
    structure_candidate = "structure_candidate"
    summarise_confirmation = "summarise_confirmation"
    suggest_conditions = "suggest_conditions"
    review_summary = "review_summary"
    advisory_wording = "advisory_wording"


class ModelAssistRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assist_id: str
    provider: str
    model_name: str
    model_url: str
    purpose: AssistPurpose
    prompt_template: str
    input_refs: list[str] = Field(default_factory=list)
    output_ref: str | None = None
    output_format: str = "json"
    output: Any | None = None
    used_live_model: bool = False
    created_at: str = Field(default_factory=clock.now_iso)
    human_review_required: bool = True
    human_review_status: str = "pending"
    chap_artefact_ref: str | None = None
    chap_evidence_ref: int | None = None


# --- Suggested structured outputs (all advisory drafts) ------------------------
class WhisperDraft(BaseModel):
    question: str
    follow_ups: list[str] = Field(default_factory=list)


class FragmentClassification(BaseModel):
    category: str
    rationale: str = ""
    alternatives: list[str] = Field(default_factory=list)


class CandidateFragmentDraft(BaseModel):
    title: str
    content: str
    category: str
    suggested_conditions: dict[str, Any] = Field(default_factory=dict)


class SuggestedConditions(BaseModel):
    conditions: dict[str, Any] = Field(default_factory=dict)
    exclusions: list[dict[str, Any]] = Field(default_factory=list)


class ConfirmationSummary(BaseModel):
    summary: str


class ReviewSummary(BaseModel):
    summary: str
    risks_noted: list[str] = Field(default_factory=list)


class AdvisoryWording(BaseModel):
    advisory_text: str
    use_constraints: list[str] = Field(default_factory=list)
