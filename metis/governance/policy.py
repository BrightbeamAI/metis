"""Governance policy, the deterministic rules that gate promotion.

None of these decisions are made by a local model. A model may *draft* a review summary,
but promotion always requires a human Mission Group decision plus a satisfied policy.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from ..fragment.model import EvidenceStrength, TacitFragment
from ..taxonomy.categories import AuthorityLayer, SourcePathway
from ..taxonomy.mapping import NEVER_CONTROLLED

_STRENGTH_ORDER = {
    EvidenceStrength.none: 0,
    EvidenceStrength.weak: 1,
    EvidenceStrength.moderate: 2,
    EvidenceStrength.strong: 3,
}


_HIGH_RISK = {"high", "critical"}


@dataclass
class GovernancePolicy:
    consent_required_for_promotion: bool = True
    endogenous_min_recurrence: int = 3
    endogenous_min_strength: EvidenceStrength = EvidenceStrength.moderate
    # Granting authority is a collective Mission Group decision, enforced by CHAP's review
    # rule. Rejecting, holding, or re-eliciting needs one reviewer (the safe direction).
    review_rule: str = "quorum:2"
    # Promotion sets a review date; high-risk fragments are reviewed sooner.
    advisory_review_days: int = 180
    controlled_review_days: int = 365
    high_risk_review_factor: float = 0.5
    expiry_triggers: tuple[str, ...] = (
        "review date reached",
        "governing procedure revised",
        "equipment, material, or process change",
    )

    def approvals_required(self, reviewers: int) -> int:
        """Distinct approvals the review rule needs to grant authority."""
        if self.review_rule == "any_one_approves":
            return 1
        if self.review_rule == "all_approve":
            return max(reviewers, 1)
        if self.review_rule.startswith("quorum:"):
            return int(self.review_rule.split(":", 1)[1])
        raise ValueError(f"Unsupported review rule: {self.review_rule}")

    def review_due(self, fragment: TacitFragment, layer: AuthorityLayer,
                   now: _dt.datetime) -> _dt.datetime:
        """When a fragment promoted to ``layer`` at ``now`` must next be reviewed."""
        days = (self.controlled_review_days if AuthorityLayer(layer) == AuthorityLayer.controlled
                else self.advisory_review_days)
        risk = fragment.conditions.risk_class
        risks = set(risk) if isinstance(risk, list) else {risk}
        if risks & _HIGH_RISK:
            days = int(days * self.high_risk_review_factor)
        return now + _dt.timedelta(days=days)

    def can_promote(
        self,
        fragment: TacitFragment,
        target_layer: AuthorityLayer,
        *,
        change_control: dict | None = None,
        mission_group_reviewed: bool = False,
    ) -> tuple[bool, str]:
        target_layer = AuthorityLayer(target_layer)
        if target_layer == AuthorityLayer.evidence:
            return False, "Evidence is not a promotion target."

        # Endogenous fragments must never self-promote; they require Mission Group review
        # and a higher evidence bar.
        if fragment.source_pathway == SourcePathway.endogenous:
            if not mission_group_reviewed:
                return False, "Endogenous fragments cannot self-promote; Mission Group review is required."
            if fragment.evidence.recurrence_count < self.endogenous_min_recurrence:
                return False, f"Endogenous fragment needs recurrence >= {self.endogenous_min_recurrence}."
            if _STRENGTH_ORDER[fragment.evidence.evidence_strength] < _STRENGTH_ORDER[self.endogenous_min_strength]:
                return False, f"Endogenous fragment needs evidence strength >= {self.endogenous_min_strength.value}."

        if self.consent_required_for_promotion and not fragment.consent.permits_promotion():
            return False, "Consent is not valid and no policy exception is recorded."

        if target_layer == AuthorityLayer.controlled:
            if fragment.category in NEVER_CONTROLLED:
                return False, f"Category {fragment.category} must never become controlled instruction."
            if not change_control:
                return False, "Controlled-layer promotion requires change-control metadata."

        return True, "policy satisfied"
