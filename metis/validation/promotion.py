"""Promotion records (tacit.promotion_record)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .. import clock
from ..taxonomy.categories import AuthorityLayer, ValidationState


class PromotionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    from_layer: AuthorityLayer
    to_layer: AuthorityLayer
    new_state: ValidationState
    promoted_by: str  # CHAP group/human URI
    approvers: list[str] = Field(default_factory=list)  # human reviewers who approved
    decision_rule: str | None = None  # the CHAP review rule that the approvals satisfied
    review_ref: str | None = None
    change_control: dict | None = None
    rationale: str = ""
    promoted_at: str = Field(default_factory=clock.now_iso)
