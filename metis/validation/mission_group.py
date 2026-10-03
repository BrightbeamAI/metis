"""The Mission Group performs Tier-2 review.

It appears on the CHAP record as a *group* participant, and its decisions are made by named
human reviewers under the policy's review rule (``quorum:2`` by default), which the CHAP
coordinator enforces.
"""
from __future__ import annotations

from .tier2 import MissionGroupReview


class MissionGroup:
    def __init__(self, uri: str = "group:mission-group@metis.local",
                 members: list[str] | None = None) -> None:
        self.uri = uri
        self.members = list(members or [])

    def reviewers(self) -> list[str]:
        """The participants a Tier-2 review is addressed to."""
        return self.members or [self.uri]

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
