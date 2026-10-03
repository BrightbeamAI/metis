"""Rejection records (tacit.rejection_record). A rejected fragment stays on the chain for audit."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .. import clock


class RejectionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    rejected_by: str  # CHAP group/human URI
    reason: str
    review_ref: str | None = None
    retained_for_audit: bool = True
    rejected_at: str = Field(default_factory=clock.now_iso)
