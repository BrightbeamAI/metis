"""Tier-2 Mission Group review.

Tier-2 weighs description fidelity, operational relevance, normative alignment, and the
risk/consent/evidence dimensions before deciding the authority layer. A local model may
draft a review *summary*, but it never makes the decision.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .. import clock

TIER2_DIMENSIONS = [
    "description_fidelity",
    "operational_relevance",
    "normative_alignment",
    "safety_risk",
    "quality_risk",
    "compliance_risk",
    "fairness_equity_risk",
    "surveillance_risk",
    "evidence_strength",
    "recurrence",
    "counterexamples",
    "conditions_of_applicability",
    "consent_status",
    "review_date_and_expiry",
]

TIER2_OUTCOMES = {
    "promoted_to_advisory",
    "promoted_to_controlled",
    "held",
    "rejected",
    "re_elicit",
}


class MissionGroupReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    outcome: str
    reviewers: list[str] = Field(default_factory=list)  # CHAP group/human URIs
    dimension_assessments: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    model_assist_ref: str | None = None  # the draft summary, if a model helped
    reviewed_at: str = Field(default_factory=clock.now_iso)

    def model_post_init(self, __context) -> None:  # noqa: D401
        if self.outcome not in TIER2_OUTCOMES:
            raise ValueError(f"Unknown Tier-2 outcome: {self.outcome}")
