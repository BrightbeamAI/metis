"""Tier-1 confirmation, descriptive fidelity only.

Tier-1 answers a single question: did the system faithfully represent what the worker
meant or did? It does NOT decide whether the fragment should influence future work.
"""
from __future__ import annotations

from enum import Enum

from ..taxonomy.categories import ValidationState


class OperatorResponse(str, Enum):
    confirm = "confirm"
    correct = "correct"
    dismiss = "dismiss"
    defer = "defer"


def tier1_outcome(response: OperatorResponse) -> ValidationState | None:
    """Map an operator response to the resulting validation state (or None to not store)."""
    response = OperatorResponse(response)
    if response in (OperatorResponse.confirm, OperatorResponse.correct):
        return ValidationState.tier1_confirmed
    if response == OperatorResponse.dismiss:
        return ValidationState.rejected
    return None  # defer: keep as captured, ask again later
