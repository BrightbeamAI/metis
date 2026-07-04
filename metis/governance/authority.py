"""Authority-layer rules.

Evidence  : may support learning/review; never operational advice; never agent-visible.
Advisory  : conditional decision support under matching conditions; agent-visible as context.
Controlled: formally incorporated; requires change-control metadata and exact matching.
"""
from __future__ import annotations

from ..taxonomy.categories import AuthorityLayer, ValidationState

OPERATIONAL_LAYERS = {AuthorityLayer.advisory, AuthorityLayer.controlled}


def can_use_operationally(layer: AuthorityLayer) -> bool:
    return AuthorityLayer(layer) in OPERATIONAL_LAYERS


def can_be_agent_visible(layer: AuthorityLayer) -> bool:
    # Evidence-layer fragments must never become agent-visible tacit memory.
    return AuthorityLayer(layer) in OPERATIONAL_LAYERS


def layer_for_outcome(outcome: str) -> AuthorityLayer:
    if outcome == "promoted_to_controlled":
        return AuthorityLayer.controlled
    if outcome == "promoted_to_advisory":
        return AuthorityLayer.advisory
    return AuthorityLayer.evidence


def state_for_outcome(outcome: str) -> ValidationState:
    return {
        "promoted_to_advisory": ValidationState.promoted_to_advisory,
        "promoted_to_controlled": ValidationState.promoted_to_controlled,
        "held": ValidationState.held,
        "rejected": ValidationState.rejected,
        "re_elicit": ValidationState.re_elicit,
    }[outcome]
