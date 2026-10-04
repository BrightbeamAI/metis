"""Escalation of retrieval decisions to a person.

When tacit guidance would be applied outside the envelope a fragment records, or the
situation's risk class calls for human judgement, the decision goes to a person. The gate
flags those cases (``escalate``); this module turns them into one CHAP task per retrieval and
into required human actions that an agent must honour.
"""
from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .blocked_reasons import BlockedReason

_RISK = BlockedReason.risk_class_requires_human_escalation.value


class EscalationOutcome(str, Enum):
    applies = "applies"                  # the guidance applies in this situation
    does_not_apply = "does_not_apply"    # the guidance must not be used here
    refer_to_review = "refer_to_review"  # the Mission Group should look at the fragment again


class EscalationDecision(BaseModel):
    """The content of a ``tacit.escalation_decision``: a person's decision on an escalated
    retrieval. It concerns this situation only; changing what a fragment may do stays with the
    Mission Group."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    outcome: EscalationOutcome
    decided_by: str
    rationale: str
    fragments: list[str] = Field(default_factory=list)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None
    review_tasks: list[str] = Field(default_factory=list)


def escalation_actions(items: Sequence[Any], task_id: str | None = None) -> list[str]:
    """Required human actions for escalated blocked items (BlockedItem or BlockedTacitMemory)."""
    suffix = f" Escalation task: {task_id}." if task_id else ""
    actions: list[str] = []
    for item in items:
        ref = item.fragment_id or getattr(item, "memory_id", None) or "fragment"
        if item.reason == _RISK:
            actions.append(f"A person decides before {ref} is used: the current risk class "
                           f"requires human judgement ({item.detail}).{suffix}")
        else:
            actions.append(f"A person decides whether {ref} applies: it matches this equipment "
                           f"or product, and the situation differs ({item.detail}).{suffix}")
    return actions


def open_escalation(adapter: Any, *, requester: str, assignee: str,
                    runtime_context: dict[str, Any], items: Sequence[Any],
                    origin_task: str | None = None) -> str | None:
    """Open one ``tacit.escalation`` CHAP task covering every escalated item; return its id."""
    if not items:
        return None
    return adapter.create_task(
        "tacit.escalation", assignee=assignee, delegator=requester,
        task_input={
            "runtime_context": runtime_context,
            "origin_task": origin_task,
            "fragments": [{"fragment_id": i.fragment_id, "reason": i.reason, "detail": i.detail}
                          for i in items],
        })
