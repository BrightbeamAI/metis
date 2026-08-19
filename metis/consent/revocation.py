"""Revocation and supersession records (carried as tacit.revocation_record /
tacit.supersession_record artefacts via a CHAP control event)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .. import clock
from ..taxonomy.categories import RevocationStatus


class RevocationReason(str, Enum):
    consent_withdrawn = "consent_withdrawn"
    rejected = "rejected"
    superseded = "superseded"
    safety_concern = "safety_concern"
    drift = "drift"
    retired = "retired"
    re_elicitation = "re_elicitation"


class RevocationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    new_status: RevocationStatus
    reason: RevocationReason
    actioned_by: str  # CHAP participant URI
    note: str | None = None
    retention_audit_only: bool = True  # the record is retained for audit, never deleted
    superseded_by: str | None = None  # fragment_id of the replacement
    actioned_at: str = Field(default_factory=clock.now_iso)


def blocks_retrieval(status: RevocationStatus) -> bool:
    return RevocationStatus(status) != RevocationStatus.active
