"""Governed guidance for agents, and the escalations it hands to people."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import guidance as views
from ...governance.membership import Role
from ...identity import Principal
from ..access import require
from ..deps import principal, repository
from ..schemas import AgentContextIn, RetrieveIn

router = APIRouter(tags=["agents"])


@router.post("/v1/workspaces/{workspace_id}/retrieve",
             summary="Governed guidance for the current work situation (agent)")
def retrieve(workspace_id: str, body: RetrieveIn, p: Principal = Depends(principal),
             repo: Any = Depends(repository)) -> dict[str, Any]:
    """Returns only guidance whose recorded conditions match ``context``, with its use
    constraints, plus anything a person must decide. The decision is recorded on the
    workspace's CHAP chain under the calling agent's identity."""
    def ask(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.agent)
        decision = engine.retrieve(views.context_from(body.context), role=body.role,
                                   requester=p.uri)
        return views.guidance_view(engine, decision)
    return repo.write(workspace_id, ask)


@router.post("/v1/workspaces/{workspace_id}/agent-context",
             summary="Procedural, semantic, episodic, and gated tacit memory for a task (agent)")
def agent_context(workspace_id: str, body: AgentContextIn, p: Principal = Depends(principal),
                  repo: Any = Depends(repository)) -> dict[str, Any]:
    def ask(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.agent)
        amc = engine.agent_context(body.task, views.context_from(body.context), role=body.role,
                                   requester=p.uri)
        return views.agent_context_view(engine, amc)
    return repo.write(workspace_id, ask)


@router.get("/v1/workspaces/{workspace_id}/memory",
            summary="Agent-visible tacit memory: metadata only")
def memory(workspace_id: str, p: Principal = Depends(principal),
           repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    def view(engine: Any) -> list[dict[str, Any]]:
        require(engine, p, Role.agent, Role.reviewer, Role.auditor, Role.admin,
                global_auditor=True)
        return views.memory_listing(engine)
    return repo.read(workspace_id, view)


@router.get("/v1/workspaces/{workspace_id}/escalations",
            summary="Retrievals the gate handed to a person")
def escalations(workspace_id: str, open_only: bool = True, p: Principal = Depends(principal),
                repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    def view(engine: Any) -> list[dict[str, Any]]:
        require(engine, p, Role.escalation, Role.reviewer, Role.auditor, Role.admin,
                global_auditor=True)
        ws = engine.adapter.coord.get_workspace(engine.adapter.workspace_id)
        out = []
        for task in (ws.tasks.values() if ws else []):
            if task.kind != "tacit.escalation":
                continue
            if open_only and task.state in ("completed", "cancelled", "declined", "superseded"):
                continue
            out.append({"task_id": task.id, "state": task.state, "assignee": task.assignee,
                        "requested_by": task.delegator, "created_at": task.created_at,
                        "runtime_context": task.input.get("runtime_context"),
                        "fragments": task.input.get("fragments", []),
                        "origin_task": task.input.get("origin_task")})
        return sorted(out, key=lambda t: t["created_at"])
    return repo.read(workspace_id, view)
