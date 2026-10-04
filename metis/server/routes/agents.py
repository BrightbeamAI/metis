"""Governed guidance for agents, and the escalations it hands to people."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...governance.membership import Role
from ...identity import Principal
from .. import operations as ops
from ..access import require
from ..deps import principal, repository
from ..schemas import AgentContextIn, EscalationDecisionIn, RetrieveIn

router = APIRouter(tags=["agents"])


@router.post("/v1/workspaces/{workspace_id}/retrieve",
             summary="Governed guidance for the current work situation (agent)")
def retrieve(workspace_id: str, body: RetrieveIn, p: Principal = Depends(principal),
             repo: Any = Depends(repository)) -> dict[str, Any]:
    """Returns only guidance whose recorded conditions match ``context``, with its use
    constraints, plus anything a person must decide. The decision is recorded on the
    workspace's CHAP chain under the calling agent's identity."""
    return ops.retrieve(repo, p, workspace_id, body.context, body.role)


@router.post("/v1/workspaces/{workspace_id}/agent-context",
             summary="Procedural, semantic, episodic, and gated tacit memory for a task (agent)")
def agent_context(workspace_id: str, body: AgentContextIn, p: Principal = Depends(principal),
                  repo: Any = Depends(repository)) -> dict[str, Any]:
    return ops.agent_context(repo, p, workspace_id, body.task, body.context, body.role)


@router.get("/v1/workspaces/{workspace_id}/memory",
            summary="Agent-visible tacit memory: metadata only")
def memory(workspace_id: str, p: Principal = Depends(principal),
           repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    return ops.memory(repo, p, workspace_id)


@router.get("/v1/workspaces/{workspace_id}/escalations",
            summary="Retrievals the gate handed to a person")
def escalations(workspace_id: str, open_only: bool = True, p: Principal = Depends(principal),
                repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    def view(engine: Any) -> list[dict[str, Any]]:
        require(engine, p, Role.escalation, Role.reviewer, Role.auditor, Role.admin,
                global_auditor=True)
        return engine.escalation_tasks(open_only=open_only)
    return repo.read(workspace_id, view)


@router.get("/v1/workspaces/{workspace_id}/escalations/{task_id}",
            summary="One escalation and its decision, for people and the agent that asked")
def escalation(workspace_id: str, task_id: str, p: Principal = Depends(principal),
               repo: Any = Depends(repository)) -> dict[str, Any]:
    return ops.escalation(repo, p, workspace_id, task_id)


@router.post("/v1/workspaces/{workspace_id}/escalations/{task_id}/decision",
             summary="Decide an escalated retrieval (escalation)")
def decide_escalation(workspace_id: str, task_id: str, body: EscalationDecisionIn,
                      p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    """``applies`` and ``does_not_apply`` decide this situation only; ``refer_to_review`` also
    opens a Mission Group review of each fragment involved."""
    def record(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.escalation)
        return engine.decide_escalation(task_id, body.outcome, by=p.uri,
                                        rationale=body.rationale)["decision"]
    return repo.write(workspace_id, record)
