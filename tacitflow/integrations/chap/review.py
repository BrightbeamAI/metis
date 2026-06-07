"""review/1.0 profile helpers.

Mission Group (Tier-2) validation and operator confirmation use CHAP's review capability:
``review.request`` then ``decide.approve`` / ``decide.reject`` / ``abstain.declare`` /
``escalate.raise``. TacitFlow adds NO parallel review system.
"""
from __future__ import annotations

REVIEW_REQUEST = "review.request"
DECIDE_APPROVE = "decide.approve"
DECIDE_REJECT = "decide.reject"
DECIDE_OVERRIDE = "decide.override"
ABSTAIN_DECLARE = "abstain.declare"
ESCALATE_RAISE = "escalate.raise"

# Mission Group Tier-2 outcomes mapped onto CHAP review/decide methods.
OUTCOME_TO_METHOD = {
    "promoted_to_advisory": DECIDE_APPROVE,
    "promoted_to_controlled": DECIDE_APPROVE,
    "rejected": DECIDE_REJECT,
    "held": ABSTAIN_DECLARE,
    "re_elicit": ESCALATE_RAISE,
}
