"""Promotion records (tacit.promotion_record)."""
from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, ConfigDict, Field

from ..taxonomy.categories import AuthorityLayer, ValidationState


class PromotionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    from_layer: AuthorityLayer
    to_layer: AuthorityLayer
    new_state: ValidationState
    promoted_by: str  # CHAP group/human URI
    review_ref: str | None = None
    change_control: dict | None = None
    rationale: str = ""
    promoted_at: str = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat())
