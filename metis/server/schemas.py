"""Request bodies of the Metis server API.

No request names the identity it acts as: the server takes it from sign-in.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..consent.contestability import ContestAction
from ..governance.membership import Role


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemberIn(_Body):
    uri: str
    roles: list[Role]
    display_name: str | None = None


class WorkspaceCreate(_Body):
    id: str = Field(description="wsp_ followed by lowercase letters, digits, - or _")
    name: str
    site: str = "site"
    review_rule: str = Field("quorum:2", description="any_one_approves, all_approve, or quorum:<n>")
    whisper_deadline_hours: int | None = Field(None, ge=1)
    members: list[MemberIn] = Field(default_factory=list)


class MemberUpdate(_Body):
    uri: str
    roles: list[Role] = Field(description="The member's roles afterwards; empty removes them")
    display_name: str | None = None
    reason: str | None = None


class ObservationIn(_Body):
    observation_id: str
    work_as_done: str
    context: dict[str, Any]
    worker: str | None = Field(None, description="The worker to ask; defaults to the caller")
    work_as_imagined: str | None = None
    category: str | None = None
    title: str | None = None
    supersedes: str | None = Field(None, description="A fragment awaiting re-elicitation that "
                                                     "this capture replaces")


class WhisperAnswerIn(_Body):
    response: Literal["confirm", "correct", "dismiss", "defer"]
    consent: Literal["granted", "declined"]
    corrected_text: str | None = None
    free_text: str | None = None


class ContestIn(_Body):
    action: ContestAction
    rationale: str
    proposed_correction: str | None = None


class WithdrawIn(_Body):
    note: str | None = None


class RetireIn(_Body):
    reason: Literal["retired", "drift", "safety_concern"] = "retired"
    note: str | None = None


class ReviewRequestIn(_Body):
    reason: str = ""


class VoteIn(_Body):
    outcome: Literal["promoted_to_advisory", "promoted_to_controlled", "held", "rejected",
                     "re_elicit"]
    summary: str = ""
    change_control: dict[str, Any] | None = None
    dimension_assessments: dict[str, str] | None = None
    use_constraints: list[str] | None = Field(
        None, description="Constraints that travel with a promoted fragment; the first approval "
                          "proposes them")


class RetrieveIn(_Body):
    context: dict[str, Any]
    role: str | None = None


class AgentContextIn(_Body):
    task: str
    context: dict[str, Any]
    role: str | None = None
