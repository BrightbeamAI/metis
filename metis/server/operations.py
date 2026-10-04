"""What agents and capture sources do, shared by the HTTP API and the remote MCP endpoint.

Each operation takes the repository, the signed-in principal, and its arguments, checks the
principal's roles in the workspace, and runs as a read or as the workspace's one writer. Both
surfaces call these, so they apply the same rules.
"""
from __future__ import annotations

from typing import Any

from .. import guidance as views
from ..consent.model import ConsentRecord, ConsentStatus
from ..governance.membership import Role
from ..identity import Principal
from .access import Forbidden, require, require_member, roles_in
from .deps import NotFound


def workspaces(repo: Any, p: Principal) -> list[dict[str, Any]]:
    """The workspaces the caller can see, with the caller's roles in each."""
    mine = repo.memberships(p.uri)
    return [{"id": w.id, "name": w.name, "site": w.site, "created_at": w.created_at,
             "updated_at": w.updated_at, "your_roles": mine.get(w.id, [])}
            for w in repo.list() if p.is_auditor or w.id in mine]


def describe(repo: Any, p: Principal, workspace_id: str) -> dict[str, Any]:
    def view(engine: Any) -> dict[str, Any]:
        roles = require_member(engine, p)
        chain = engine.verify()
        return {**engine.adapter.descriptor(),
                "review_rule": engine.governance.policy.review_rule,
                "reviewers": len(engine.mission_group_members),
                "escalation_assignee": engine.escalation_assignee,
                "whisper_deadline_ms": engine.capture.whisper_deadline_ms,
                "agent_visible_memory": len(views.visible_memory(engine)),
                "evidence_verified": chain.ok,
                "your_roles": sorted(r.value for r in roles)}
    return repo.read(workspace_id, view)


def retrieve(repo: Any, p: Principal, workspace_id: str, context: dict[str, Any],
             role: str | None = None) -> dict[str, Any]:
    """Governed guidance for a work situation, recorded under the agent's identity."""
    def ask(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.agent)
        decision = engine.retrieve(views.context_from(context), role=role, requester=p.uri)
        return views.guidance_view(engine, decision)
    return repo.write(workspace_id, ask)


def agent_context(repo: Any, p: Principal, workspace_id: str, task: str, context: dict[str, Any],
                  role: str | None = None) -> dict[str, Any]:
    def ask(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.agent)
        amc = engine.agent_context(task, views.context_from(context), role=role, requester=p.uri)
        return views.agent_context_view(engine, amc)
    return repo.write(workspace_id, ask)


def memory(repo: Any, p: Principal, workspace_id: str) -> list[dict[str, Any]]:
    def view(engine: Any) -> list[dict[str, Any]]:
        require(engine, p, Role.agent, Role.reviewer, Role.auditor, Role.admin,
                global_auditor=True)
        return views.memory_listing(engine)
    return repo.read(workspace_id, view)


def escalation(repo: Any, p: Principal, workspace_id: str, task_id: str) -> dict[str, Any]:
    """One escalation and any decision on it, for people and for the agent that asked."""
    def view(engine: Any) -> dict[str, Any]:
        item = next((t for t in engine.escalation_tasks(open_only=False)
                     if t["task_id"] == task_id), None)
        readers = {Role.escalation, Role.reviewer, Role.auditor, Role.admin}
        if item is None or not (roles_in(engine, p) & readers or p.is_auditor
                                or item["requested_by"] == p.uri):
            raise NotFound(f"No escalation {task_id}.")
        return item
    return repo.read(workspace_id, view)


def whisper_view(engine: Any, pending: Any) -> dict[str, Any]:
    prompt = engine.adapter.artefacts.get(pending.whisper_id) or {}
    return {"whisper_id": pending.whisper_id, "worker": pending.worker,
            "question": pending.whisper.question,
            "options": [o["id"] for o in pending.whisper.options],
            "observation": pending.observation.work_as_done or pending.observation.text,
            "candidate": {"category": pending.candidate.category,
                          "hypothesis": pending.candidate.hypothesis},
            "submitted_by": pending.submitted_by or pending.worker,
            "asked_at": prompt.get("produced_at")}


def submit_observation(repo: Any, p: Principal, workspace_id: str, *, observation_id: str,
                       work_as_done: str, context: dict[str, Any], worker: str | None = None,
                       work_as_imagined: str | None = None, category: str | None = None,
                       title: str | None = None, supersedes: str | None = None) -> dict[str, Any]:
    """Report where a worker's action differed from the procedure. A capture source may report
    for any worker member; a worker may report their own work. Nothing is stored until the
    worker answers the whisper."""
    def capture(engine: Any) -> dict[str, Any]:
        roles = roles_in(engine, p)
        asked = worker or p.uri
        if Role.capture not in roles and not (Role.worker in roles and asked == p.uri):
            raise Forbidden("Reporting an observation needs the capture role, or the worker role "
                            "for your own work.")
        if Role.worker not in engine.roles_of(asked):
            raise Forbidden(f"{asked} is not a worker in {workspace_id}.")
        ctx = views.context_from(context)
        pending = engine.begin_capture(
            {"observation_id": observation_id, "work_as_imagined": work_as_imagined,
             "work_as_done": work_as_done, "context": ctx, "source": "api"},
            consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=asked,
            submitted_by=None if asked == p.uri else p.uri, category=category, title=title,
            conditions=ctx, supersedes=supersedes)
        if pending.deferred:
            return {"deferred": True, "reason": pending.deferred_reason, "worker": asked,
                    "note": "The worker has reached the whisper budget; nothing was asked."}
        return {"deferred": False, **whisper_view(engine, pending)}
    return repo.write(workspace_id, capture)
