"""The closed set of reasons the retrieval gate may block a fragment or memory object."""
from __future__ import annotations

from enum import Enum


class BlockedReason(str, Enum):
    evidence_layer_not_authorised = "evidence_layer_not_authorised"
    tier2_validation_missing = "tier2_validation_missing"
    conditions_do_not_match = "conditions_do_not_match"
    expired_review_date = "expired_review_date"
    consent_withdrawn = "consent_withdrawn"
    controlled_layer_requires_exact_match = "controlled_layer_requires_exact_match"
    risk_class_requires_human_escalation = "risk_class_requires_human_escalation"
    endogenous_fragment_requires_review = "endogenous_fragment_requires_review"
    revoked_or_superseded = "revoked_or_superseded"
    role_not_authorised = "role_not_authorised"
    exclusion_condition_applies = "exclusion_condition_applies"


HUMAN_READABLE: dict[BlockedReason, str] = {
    BlockedReason.evidence_layer_not_authorised: "Fragment is in the Evidence layer and cannot be used for operational advice.",
    BlockedReason.tier2_validation_missing: "Fragment has not passed Tier-2 Mission Group validation.",
    BlockedReason.conditions_do_not_match: "The fragment's conditions of applicability do not match the current context.",
    BlockedReason.expired_review_date: "The fragment's review date or validity window has elapsed.",
    BlockedReason.consent_withdrawn: "Consent for this fragment has been withdrawn.",
    BlockedReason.controlled_layer_requires_exact_match: "Controlled-layer fragments require exact condition matching.",
    BlockedReason.risk_class_requires_human_escalation: "The current risk class requires human escalation; the agent must not act on tacit guidance alone.",
    BlockedReason.endogenous_fragment_requires_review: "Endogenous (agent-surfaced) fragment requires Mission Group review before operational use.",
    BlockedReason.revoked_or_superseded: "The fragment has been revoked, withdrawn, superseded, or retired.",
    BlockedReason.role_not_authorised: "The requesting role is not authorised to retrieve this fragment.",
    BlockedReason.exclusion_condition_applies: "An exclusion condition applies in the current context.",
}
