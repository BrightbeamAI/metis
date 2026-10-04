"""The caller, workspaces, and workspace members."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from ...governance.membership import Member, Role
from ...identity import Principal
from ...storage.repository import WorkspaceSettings
from ..access import Forbidden, require, require_member, roles_in
from ..deps import principal, repository, settings
from ..schemas import MemberUpdate, WorkspaceCreate

router = APIRouter(tags=["workspaces"])


def _member_view(member: Member) -> dict[str, Any]:
    return {"uri": member.uri, "roles": [r.value for r in member.roles],
            "display_name": member.display_name}


@router.get("/v1/me", summary="The signed-in caller and their workspaces")
def me(p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    names = {w.id: w.name for w in repo.list()}
    return {
        "uri": p.uri,
        "display_name": p.display_name,
        "sign_in": p.method,
        "global_roles": sorted(p.global_roles),
        "workspaces": [{"id": wid, "name": names.get(wid, wid), "roles": roles}
                       for wid, roles in repo.memberships(p.uri).items()],
    }


@router.get("/v1/workspaces", summary="Workspaces the caller can see")
def list_workspaces(p: Principal = Depends(principal),
                    repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    mine = repo.memberships(p.uri)
    return [{"id": w.id, "name": w.name, "site": w.site, "created_at": w.created_at,
             "updated_at": w.updated_at, "your_roles": mine.get(w.id, [])}
            for w in repo.list() if p.is_auditor or w.id in mine]


@router.post("/v1/workspaces", status_code=status.HTTP_201_CREATED,
             summary="Create a workspace (global admin)")
def create_workspace(body: WorkspaceCreate, p: Principal = Depends(principal),
                     repo: Any = Depends(repository), cfg: Any = Depends(settings)) -> dict[str, Any]:
    if not p.is_admin:
        raise Forbidden("Creating a workspace needs the global admin role.")
    hours = body.whisper_deadline_hours or cfg.whisper_deadline_hours
    ws = WorkspaceSettings(
        id=body.id, name=body.name, site=body.site, review_rule=body.review_rule,
        whisper_deadline_ms=hours * 60 * 60 * 1000,
        members=[Member(uri=m.uri, roles=m.roles, display_name=m.display_name)
                 for m in body.members])
    return repo.create(ws, by=p.uri)


@router.get("/v1/workspaces/{workspace_id}", summary="Describe a workspace")
def describe_workspace(workspace_id: str, p: Principal = Depends(principal),
                       repo: Any = Depends(repository)) -> dict[str, Any]:
    def view(engine: Any) -> dict[str, Any]:
        roles = require_member(engine, p)
        chain = engine.verify()
        return {**engine.adapter.descriptor(),
                "review_rule": engine.governance.policy.review_rule,
                "reviewers": len(engine.mission_group_members),
                "escalation_assignee": engine.escalation_assignee,
                "whisper_deadline_ms": engine.capture.whisper_deadline_ms,
                "evidence_verified": chain.ok,
                "your_roles": sorted(r.value for r in roles)}
    return repo.read(workspace_id, view)


@router.get("/v1/workspaces/{workspace_id}/members", summary="List members and their roles")
def list_members(workspace_id: str, p: Principal = Depends(principal),
                 repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    def view(engine: Any) -> list[dict[str, Any]]:
        require(engine, p, Role.admin, Role.reviewer, Role.auditor, global_auditor=True)
        return [_member_view(m) for m in engine.members.values()]
    return repo.read(workspace_id, view)


@router.put("/v1/workspaces/{workspace_id}/members",
            summary="Set a member's roles; an empty list removes the member")
def set_member(workspace_id: str, body: MemberUpdate, p: Principal = Depends(principal),
               repo: Any = Depends(repository)) -> dict[str, Any]:
    def change(engine: Any) -> dict[str, Any]:
        if Role.admin not in roles_in(engine, p) and not p.is_admin:
            raise Forbidden(f"Managing members of {workspace_id} needs its admin role.")
        member = engine.set_member(body.uri, list(body.roles), by=p.uri,
                                   display_name=body.display_name, reason=body.reason)
        return ({"removed": True, "uri": body.uri} if member is None
                else {"removed": False, **_member_view(member)})
    return repo.write(workspace_id, change)
