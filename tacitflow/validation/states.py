"""The validation state machine.

Tier-1 confirmation concerns descriptive fidelity only. Tier-2 Mission Group review decides
the organisational role a fragment may play. Transitions are explicit and auditable; no
local model output may move a fragment between states.
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
    VS.promoted_to_advisory: {VS.promoted_to_controlled, VS.withdrawn, VS.superseded, VS.expired, VS.held},
    VS.promoted_to_controlled: {VS.withdrawn, VS.superseded, VS.expired, VS.held},
    VS.rejected: set(),
    VS.withdrawn: set(),
    VS.superseded: set(),
    VS.expired: {VS.tier2_pending},  # re-review can revive an expired fragment
}


def can_transition(current: ValidationState, target: ValidationState) -> bool:
    return ValidationState(target) in VALID_TRANSITIONS.get(ValidationState(current), set())


class InvalidTransition(ValueError):
    pass


def assert_transition(current: ValidationState, target: ValidationState) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(f"Illegal validation transition: {current} -> {target}")
