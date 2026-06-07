"""Rejection records (tacit.rejection_record). Rejected fragments are retained, never deleted."""
from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, ConfigDict, Field


class RejectionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    rejected_by: str  # CHAP group/human URI
    reason: str
    review_ref: str | None = None
    retained_for_audit: bool = True
    rejected_at: str = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat())
