"""Re-elicitation requests (tacit.re_elicitation_request)."""
from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, ConfigDict, Field


class ReElicitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    requested_by: str  # CHAP group/human URI
    reason: str
    what_to_clarify: str | None = None
    review_ref: str | None = None
    requested_at: str = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat())
