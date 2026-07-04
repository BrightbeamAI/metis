"""Structured conditions / context.

A :class:`TacitContext` plays two roles: it records a fragment's *conditions of
applicability*, and it describes the *runtime situation* presented to the retrieval gate.
Conditions are structured, never free text, so eligibility is deterministic and auditable.
"""
from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, ConfigDict, Field

Scalar = str | list[str]

# The structured context keys compared by the matcher.
CONTEXT_KEYS = (
    "site", "area", "line", "equipment_family", "equipment_id", "product_family",
    "material_lot", "operating_mode", "shift_pattern", "role", "risk_class", "trigger_context",
)


class TacitContext(BaseModel):
    """Structured conditions of applicability / runtime context."""

    model_config = ConfigDict(extra="forbid")

    site: Scalar | None = None
    area: Scalar | None = None
    line: Scalar | None = None
    equipment_family: Scalar | None = None
    equipment_id: Scalar | None = None
    product_family: Scalar | None = None
    material_lot: Scalar | None = None
    operating_mode: Scalar | None = None
    shift_pattern: Scalar | None = None
    role: Scalar | None = None
    risk_class: str | None = None
    trigger_context: Scalar | None = None
    environmental_conditions: dict[str, Scalar] = Field(default_factory=dict)
    exclusion_conditions: list[dict[str, Scalar]] = Field(default_factory=list)
    valid_from: _dt.datetime | None = None
    valid_until: _dt.datetime | None = None

    def constrained_keys(self) -> list[str]:
        """Context keys this object actually constrains (non-None)."""
        return [k for k in CONTEXT_KEYS if getattr(self, k) is not None]
