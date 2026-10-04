"""Fragments, contests, retirement, and Mission Group review."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ... import clock
from ...consent.revocation import RevocationReason
from ...governance.membership import Role
from ...guidance import overdue
from ...identity import Principal
from ...taxonomy.categories import RevocationStatus, ValidationState
from ..access import (
    FRAGMENT_READERS,
    Forbidden,
    can_read_fragment,
    contributed,
    require,
    require_member,
    roles_in,
)
from ..deps import NotFound, principal, repository
from ..schemas import ContestIn, RetireIn, ReviewRequestIn, VoteIn, WithdrawIn

router = APIRouter(tags=["fragments"])

_IN_USE = (ValidationState.promoted_to_advisory, ValidationState.promoted_to_controlled)


def fragment_view(fragment: Any) -> dict[str, Any]:
    return fragment.model_dump(mode="json")


def _fragment_for(engine: Any, p: Principal, fragment_id: str) -> Any:
    """The fragment, if the caller may read it; otherwise ``NotFound``, so its existence is
    not revealed."""
    frag = engine.fragments.get(fragment_id)
    if frag is None or not can_read_fragment(engine, p, frag):
        raise NotFound(f"No fragment {fragment_id}.")
    return frag


def _jsonable(result: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in result.items():
        if key == "memory" and value is not None:
            out["memory_id"] = value.memory_id
        elif hasattr(value, "model_dump"):
            out[key] = value.model_dump(mode="json")
        else:
            out[key] = value
    return out


@router.get("/v1/workspaces/{workspace_id}/fragments", summary="Fragments the caller may read")
def list_fragments(workspace_id: str, validation_state: str | None = None,
                   authority_layer: str | None = None, p: Principal = Depends(principal),
                   repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    """Reviewers, auditors, and workspace admins read every fragment; a worker reads the
    fragments they contributed. Agents receive guidance through retrieval instead."""
    def view(engine: Any) -> list[dict[str, Any]]:
        roles = require_member(engine, p)
        if not (roles & (FRAGMENT_READERS | {Role.worker}) or p.is_auditor):
            raise Forbidden("Agents receive governed guidance through /retrieve.")
        return [fragment_view(f) for f in engine.fragments.all()
                if can_read_fragment(engine, p, f)
                and (validation_state is None or f.validation_state.value == validation_state)
                and (authority_layer is None or f.authority_layer.value == authority_layer)]
    return repo.read(workspace_id, view)


@router.get("/v1/workspaces/{workspace_id}/fragments/{fragment_id}", summary="One fragment")
def get_fragment(workspace_id: str, fragment_id: str, p: Principal = Depends(principal),
                 repo: Any = Depends(repository)) -> dict[str, Any]:
    def view(engine: Any) -> dict[str, Any]:
        require_member(engine, p)
        frag = _fragment_for(engine, p, fragment_id)
        is_open = engine.governance.review_open(fragment_id)
        return {**fragment_view(frag), "review_open": is_open,
                "approvals": engine.governance.review_approvals(fragment_id),
                "proposal": engine.governance.proposals.get(fragment_id) if is_open else None}
    return repo.read(workspace_id, view)


@router.post("/v1/workspaces/{workspace_id}/fragments/{fragment_id}/contest",
             summary="Contest a fragment (its worker, or a reviewer)")
def contest(workspace_id: str, fragment_id: str, body: ContestIn,
            p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    """A withdrawal revokes the fragment and is the contributing worker's alone; every other
    contest joins the fragment's open review or opens one, and the reviewers decide it."""
    def record(engine: Any) -> dict[str, Any]:
        roles = roles_in(engine, p)
        frag = _fragment_for(engine, p, fragment_id)
        worker = Role.worker in roles and contributed(frag, p.uri)
        if not (worker or Role.reviewer in roles):
            raise Forbidden("Contesting a fragment needs the reviewer role, or the worker role "
                            "for a fragment you contributed.")
        out = engine.governance.contest(fragment_id, body.action, raised_by=p.uri,
                                        rationale=body.rationale,
                                        proposed_correction=body.proposed_correction)
        return {"recorded": True, "action": body.action.value,
                **{k: v for k, v in out.items() if isinstance(v, str)}}
    return repo.write(workspace_id, record)


@router.post("/v1/workspaces/{workspace_id}/fragments/{fragment_id}/withdraw",
             summary="Withdraw consent for a fragment you contributed")
def withdraw(workspace_id: str, fragment_id: str, body: WithdrawIn | None = None,
             p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    def record(engine: Any) -> dict[str, Any]:
        frag = _fragment_for(engine, p, fragment_id)
        if not contributed(frag, p.uri):
            raise Forbidden("Only the worker who contributed this fragment can withdraw consent.")
        art = engine.governance.withdraw_consent(fragment_id, by=p.uri,
                                                 note=body.note if body else None)
        return {"withdrawn": True, "revocation_record": art}
    return repo.write(workspace_id, record)


@router.post("/v1/workspaces/{workspace_id}/fragments/{fragment_id}/retire",
             summary="Retire a fragment (reviewer)")
def retire(workspace_id: str, fragment_id: str, body: RetireIn, p: Principal = Depends(principal),
           repo: Any = Depends(repository)) -> dict[str, Any]:
    def record(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.reviewer)
        _fragment_for(engine, p, fragment_id)
        art = engine.governance.revoke(fragment_id, reason=RevocationReason(body.reason),
                                       by=p.uri, note=body.note)
        return {"retired": True, "revocation_record": art}
    return repo.write(workspace_id, record)


@router.post("/v1/workspaces/{workspace_id}/fragments/{fragment_id}/reviews",
             summary="Open a Mission Group review (reviewer)")
def request_review(workspace_id: str, fragment_id: str, body: ReviewRequestIn | None = None,
                   p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    def record(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.reviewer)
        _fragment_for(engine, p, fragment_id)
        task = engine.request_review(fragment_id, by=p.uri, reason=body.reason if body else "")
        return {"review_task": task, "review_open": engine.governance.review_open(fragment_id)}
    return repo.write(workspace_id, record)


@router.post("/v1/workspaces/{workspace_id}/fragments/{fragment_id}/votes",
             summary="Record your decision on a fragment's review (reviewer)")
def vote(workspace_id: str, fragment_id: str, body: VoteIn, p: Principal = Depends(principal),
         repo: Any = Depends(repository)) -> dict[str, Any]:
    """Holding, rejecting, or sending a fragment back for re-elicitation takes one reviewer.
    An approval to promote is applied once the approvals meet the review rule; until then the
    result's status is ``pending``."""
    def record(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.reviewer)
        _fragment_for(engine, p, fragment_id)
        out = engine.cast_review_vote(fragment_id, body.outcome, reviewer=p.uri,
                                      summary=body.summary, change_control=body.change_control,
                                      dimension_assessments=body.dimension_assessments,
                                      use_constraints=body.use_constraints)
        frag = engine.fragments.require(fragment_id)
        return {**_jsonable(out), "validation_state": frag.validation_state.value,
                "authority_layer": frag.authority_layer.value}
    return repo.write(workspace_id, record)


def review_items(engine: Any, p: Principal, *, with_fragment: bool = False) -> list[dict[str, Any]]:
    """Fragments awaiting a first review, with an open review, held, or past their review date."""
    gov, now = engine.governance, clock.now_dt()
    need = gov.policy.approvals_required(len(engine.mission_group_members))
    queue = []
    for frag in engine.fragments.all():
        if frag.revocation_status != RevocationStatus.active:
            continue
        fid = frag.fragment_id
        is_open = gov.review_open(fid)
        awaiting = frag.validation_state == ValidationState.tier1_confirmed
        due = frag.validation_state in _IN_USE and overdue(frag, now)
        if not (is_open or awaiting or due or frag.validation_state == ValidationState.held):
            continue
        approvals = gov.review_approvals(fid)
        item = {
            "fragment_id": fid, "title": frag.title, "category": frag.category.value,
            "validation_state": frag.validation_state.value,
            "authority_layer": frag.authority_layer.value,
            "review_open": is_open,
            "review_task": gov.refs.get(fid, {}).get("task") if is_open else None,
            "approvals": [{"reviewer": r, "outcome": o} for r, o in approvals.items()],
            "approvals_required": need, "review_due_at": frag.review_due_at,
            "overdue": due, "your_approval": approvals.get(p.uri),
            "proposal": gov.proposals.get(fid) if is_open else None,
        }
        if with_fragment:
            item["fragment"] = fragment_view(frag)
        queue.append(item)
    return queue


@router.get("/v1/workspaces/{workspace_id}/reviews", summary="The Mission Group's review queue")
def review_queue(workspace_id: str, p: Principal = Depends(principal),
                 repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    """Fragments awaiting a first review, with an open review, held, or past their review date."""
    def view(engine: Any) -> list[dict[str, Any]]:
        require(engine, p, Role.reviewer, Role.admin, Role.auditor, global_auditor=True)
        return review_items(engine, p)
    return repo.read(workspace_id, view)
