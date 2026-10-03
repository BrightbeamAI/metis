"""The validation state machine.

Tier-1 confirmation concerns descriptive fidelity. Tier-2 Mission Group review decides the
organisational role a fragment may play, at first promotion and again whenever a fragment in
use is re-reviewed: reviewers can renew it, move it between the Advisory and Controlled layers,
hold it, reject it, or send it back for re-elicitation. Transitions are explicit and
auditable, and people make every one of them.
"""
from __future__ import annotations

from ..taxonomy.categories import ValidationState

VS = ValidationState

VALID_TRANSITIONS: dict[ValidationState, set[ValidationState]] = {
    VS.captured: {VS.worker_confirmed, VS.tier1_confirmed, VS.rejected, VS.re_elicit},
    VS.worker_confirmed: {VS.tier1_confirmed, VS.rejected, VS.re_elicit},
    VS.tier1_confirmed: {VS.tier2_pending, VS.rejected, VS.re_elicit},
    VS.tier2_pending: {
        VS.promoted_to_advisory, VS.promoted_to_controlled,
        VS.held, VS.rejected, VS.re_elicit,
    },
    VS.held: {VS.tier2_pending, VS.rejected, VS.re_elicit},
    VS.re_elicit: {VS.captured, VS.rejected},
    # A re-review of a fragment in use can renew it, move it between layers, hold it, reject
    # it, or send it back for re-elicitation.
    VS.promoted_to_advisory: {
        VS.promoted_to_advisory, VS.promoted_to_controlled, VS.held, VS.rejected, VS.re_elicit,
        VS.withdrawn, VS.superseded, VS.expired,
    },
    VS.promoted_to_controlled: {
        VS.promoted_to_controlled, VS.promoted_to_advisory, VS.held, VS.rejected, VS.re_elicit,
        VS.withdrawn, VS.superseded, VS.expired,
    },
    VS.rejected: set(),
    VS.withdrawn: set(),
    VS.superseded: set(),
    VS.expired: {
        VS.promoted_to_advisory, VS.promoted_to_controlled, VS.held, VS.rejected, VS.re_elicit,
    },
}


def can_transition(current: ValidationState, target: ValidationState) -> bool:
    return ValidationState(target) in VALID_TRANSITIONS.get(ValidationState(current), set())


class InvalidTransition(ValueError):
    pass


def assert_transition(current: ValidationState, target: ValidationState) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(f"Illegal validation transition: {current} -> {target}")
