"""Escalation of retrieval decisions to a person.

When tacit guidance would be applied outside the envelope a fragment records, or the
situation's risk class calls for human judgement, the decision goes to a person. The gate
flags those cases (``escalate``); this module turns them into one CHAP task per retrieval and
into required human actions that an agent must honour.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from dataclasses import dataclass, field
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


@dataclass
class Decided:
    """A person's recent decisions on escalations of one requester's situation."""

    applies: dict[str, str] = field(default_factory=dict)         # fragment id -> task id
    does_not_apply: dict[str, str] = field(default_factory=dict)  # fragment id -> task id


_CLOSED = ("completed", "cancelled", "declined", "superseded")


class EscalationBook:
    """The escalations of a workspace, read from its CHAP tasks.

    The same requester asking again in the same situation reuses its open escalation, so a
    person is asked once. Once a person decides, the decision holds for that requester and that
    exact situation for ``grant_hours``: guidance a person said applies is given (and the
    retrieval records whose decision it was), and guidance a person said does not apply stays
    withheld without asking again. Changing what a fragment may do in general stays with the
    Mission Group.
    """

    def __init__(self, adapter: Any, *, grant_hours: float = 12.0) -> None:
        self.adapter = adapter
        self.grant_hours = grant_hours

    def _tasks(self) -> list[Any]:
        ws = self.adapter.coord.get_workspace(self.adapter.workspace_id)
        return [t for t in (ws.tasks.values() if ws else []) if t.kind == "tacit.escalation"]

    @staticmethod
    def _same(task: Any, requester: str, runtime_context: dict[str, Any]) -> bool:
        return task.delegator == requester and task.input.get("runtime_context") == runtime_context

    def decided(self, requester: str, runtime_context: dict[str, Any],
                now: _dt.datetime) -> Decided:
        """Decisions on this requester's escalations of this situation, still in force."""
        found = Decided()
        if self.grant_hours <= 0:
            return found
        horizon = now - _dt.timedelta(hours=self.grant_hours)
        for task in sorted(self._tasks(), key=lambda t: t.created_at):
            if task.state != "completed" or not self._same(task, requester, runtime_context):
                continue
            output = task.output if isinstance(task.output, dict) else {}
            content = output.get("content") or {}
            if output.get("kind") != "tacit.escalation_decision" or not output.get("produced_at"):
                continue
            try:
                when = _dt.datetime.fromisoformat(str(output["produced_at"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=_dt.timezone.utc)
            if when < horizon:
                continue
            outcome = content.get("outcome")
            for fragment_id in content.get("fragments") or []:
                if outcome == EscalationOutcome.applies.value:
                    found.applies[fragment_id] = task.id
                    found.does_not_apply.pop(fragment_id, None)
                elif outcome in (EscalationOutcome.does_not_apply.value,
                                 EscalationOutcome.refer_to_review.value):
                    found.does_not_apply[fragment_id] = task.id
                    found.applies.pop(fragment_id, None)
        return found

    def open(self, *, requester: str, assignee: str, runtime_context: dict[str, Any],
             items: Sequence[Any], origin_task: str | None = None) -> str | None:
        """The escalation for ``items``: this requester's open escalation of the same situation
        and fragments, or a new one."""
        if not items:
            return None
        wanted = sorted(i.fragment_id for i in items)
        for task in self._tasks():
            if (task.state not in _CLOSED and self._same(task, requester, runtime_context)
                    and sorted(f.get("fragment_id") for f in task.input.get("fragments", []))
                    == wanted):
                return task.id
        return open_escalation(self.adapter, requester=requester, assignee=assignee,
                               runtime_context=runtime_context, items=items,
                               origin_task=origin_task)

    @staticmethod
    def note(fragment_id: str, task_id: str, applies: bool) -> str:
        if applies:
            return f"{fragment_id} applies here on a person's decision (escalation {task_id})."
        return f"A person decided {fragment_id} does not apply here (escalation {task_id})."
