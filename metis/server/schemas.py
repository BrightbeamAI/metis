"""Request bodies of the Metis server API.

No request names the identity it acts as: the server takes it from sign-in. Every field has a
size limit (``metis.limits``), because what Metis accepts is recorded for good.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..consent.contestability import ContestAction
from ..governance.membership import Role
from ..limits import MAX_ID, MAX_ITEMS, MAX_NAME, MAX_NOTE, MAX_TEXT, MAX_URI

Id = Annotated[str, Field(min_length=1, max_length=MAX_ID)]
Uri = Annotated[str, Field(min_length=1, max_length=MAX_URI)]
Name = Annotated[str, Field(max_length=MAX_NAME)]
Text = Annotated[str, Field(max_length=MAX_TEXT)]
Note = Annotated[str, Field(max_length=MAX_NOTE)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemberIn(_Body):
    uri: Uri
    roles: list[Role] = Field(max_length=MAX_ITEMS)
    display_name: Name | None = None


class WorkspaceCreate(_Body):
    id: str = Field(max_length=MAX_NAME,
                    description="wsp_ followed by lowercase letters, digits, - or _")
    name: Name
    site: Name = "site"
    review_rule: str = Field("quorum:2", max_length=40,
                             description="any_one_approves, all_approve, or quorum:<n>")
    whisper_deadline_hours: int | None = Field(None, ge=1, le=24 * 365)
    members: list[MemberIn] = Field(default_factory=list, max_length=500)


class MemberUpdate(_Body):
    uri: Uri
    roles: list[Role] = Field(max_length=MAX_ITEMS,
                              description="The member's roles afterwards; empty removes them")
    display_name: Name | None = None
    reason: Note | None = None


class ObservationIn(_Body):
    observation_id: Id
    work_as_done: Text = Field(min_length=1)
    context: dict[str, Any]
    worker: Uri | None = Field(None, description="The worker to ask; defaults to the caller")
    work_as_imagined: Text | None = None
    category: Name | None = None
    title: Name | None = None
    supersedes: Id | None = Field(None, description="A fragment awaiting re-elicitation that "
                                                    "this capture replaces")


class WhisperAnswerIn(_Body):
    response: Literal["confirm", "correct", "dismiss", "defer"]
    consent: Literal["granted", "declined"]
    corrected_text: Text | None = None
    free_text: Text | None = None


class ContestIn(_Body):
    action: ContestAction
    rationale: Note
    proposed_correction: Text | None = None


class WithdrawIn(_Body):
    note: Note | None = None


class RetireIn(_Body):
    reason: Literal["retired", "drift", "safety_concern"] = "retired"
    note: Note | None = None


class ReviewRequestIn(_Body):
    reason: Note = ""


class VoteIn(_Body):
    outcome: Literal["promoted_to_advisory", "promoted_to_controlled", "held", "rejected",
                     "re_elicit"]
    summary: Text = ""
    change_control: dict[Name, Note] | None = Field(None, max_length=MAX_ITEMS)
    dimension_assessments: dict[Name, Note] | None = Field(None, max_length=MAX_ITEMS)
    use_constraints: list[Note] | None = Field(
        None, max_length=MAX_ITEMS,
        description="Constraints that travel with a promoted fragment; the first approval "
                    "proposes them")


class EscalationDecisionIn(_Body):
    outcome: Literal["applies", "does_not_apply", "refer_to_review"]
    rationale: Note = Field(min_length=1,
                            description="Why, in a sentence the requester can act on")


class RetrieveIn(_Body):
    context: dict[str, Any]
    role: Name | None = None


class AgentContextIn(_Body):
    task: Note
    context: dict[str, Any]
    role: Name | None = None
