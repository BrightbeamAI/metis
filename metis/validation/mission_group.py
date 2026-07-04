"""The Mission Group is a CHAP *group* participant that performs Tier-2 review."""
from __future__ import annotations

from .tier2 import MissionGroupReview


class MissionGroup:
    def __init__(self, uri: str = "group:mission-group@metis.local") -> None:
        self.uri = uri

    def review(
        self,
        fragment_id: str,
        outcome: str,
        *,
        reviewers: list[str] | None = None,
        dimension_assessments: dict[str, str] | None = None,
        summary: str = "",
        model_assist_ref: str | None = None,
    ) -> MissionGroupReview:
        return MissionGroupReview(
            fragment_id=fragment_id,
            outcome=outcome,
            reviewers=reviewers or [self.uri],
            dimension_assessments=dimension_assessments or {},
            summary=summary,
            model_assist_ref=model_assist_ref,
        )
