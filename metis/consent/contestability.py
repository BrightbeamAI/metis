"""Contestability, workers and reviewers can challenge, correct, withdraw, supersede, or
request re-elicitation of a fragment. Each action is an auditable, CHAP-recorded event."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .. import clock


class ContestAction(str, Enum):
    challenge = "challenge"
    correct = "correct"
    withdraw = "withdraw"
    supersede = "supersede"
    request_re_elicitation = "request_re_elicitation"


class ContestabilityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    action: ContestAction
    raised_by: str  # CHAP participant URI
    rationale: str
    proposed_correction: str | None = None
    raised_at: str = Field(default_factory=clock.now_iso)
