"""Consent as a first-class, worker-visible record.

A fragment cannot be promoted beyond the Evidence layer unless consent is valid or an
explicit, recorded policy exception applies. Withdrawing consent blocks future retrieval.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ConsentStatus(str, Enum):
    not_required = "not_required"
    pending = "pending"
    granted = "granted"
    withdrawn = "withdrawn"
    policy_exception = "policy_exception"


class AttributionMode(str, Enum):
    named = "named"
    role = "role"
    anonymous = "anonymous"
    group = "group"


class Visibility(str, Enum):
    worker_only = "worker_only"
    mission_group = "mission_group"
    workspace = "workspace"
    agent_visible = "agent_visible"


class ConsentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_required: bool = True
    consent_status: ConsentStatus = ConsentStatus.pending
    attribution_mode: AttributionMode = AttributionMode.role
    visibility: Visibility = Visibility.mission_group
    withdrawal_allowed: bool = True
    withdrawal_constraints: str | None = None
    worker_visible_record: bool = True
    policy_exception: bool = False
    policy_exception_reason: str | None = None

    def permits_promotion(self) -> bool:
        """Consent permits promotion beyond Evidence when granted, not required, or an
        explicit policy exception is recorded with a reason."""
        if self.consent_status == ConsentStatus.granted:
            return True
        if self.consent_status == ConsentStatus.not_required and not self.consent_required:
            return True
        if self.policy_exception and self.policy_exception_reason:
            return True
        return False

    def permits_retrieval(self) -> bool:
        """Retrieval is blocked once consent is withdrawn."""
        return self.consent_status != ConsentStatus.withdrawn
