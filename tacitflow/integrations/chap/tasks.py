"""CHAP task construction (chap-task.schema.json, Task definition)."""
from __future__ import annotations

from typing import Any


def build_task(
    *,
    task_id: str,
    workspace: str,
    kind: str,
    assignee: str,
    delegator: str,
    created: str,
    state: str = "created",
    mode: str = "trial",
    task_input: Any | None = None,
    routing_hints: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    parent: str | None = None,
    supersedes: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": task_id,
        "workspace": workspace,
        "kind": kind,
        "state": state,
        "mode": mode,
        "assignee": assignee,
        "delegator": delegator,
        "created": created,
        "artefacts": [],
    }
    if task_input is not None:
        task["input"] = task_input
    if routing_hints:
        task["routing_hints"] = routing_hints
    if review:
        task["review"] = review
    if parent:
        task["parent"] = parent
    if supersedes:
        task["supersedes"] = supersedes
    if metadata:
        task["metadata"] = metadata
    return task
