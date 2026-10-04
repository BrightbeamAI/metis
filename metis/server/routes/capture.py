"""Capture: observations of work, and the whispers workers answer."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from ...consent.model import ConsentRecord, ConsentStatus
from ...governance.membership import Role
from ...guidance import context_from
from ...identity import Principal
from ..access import Forbidden, require, roles_in
from ..deps import NotFound, principal, repository
from ..schemas import ObservationIn, WhisperAnswerIn
from .fragments import fragment_view

router = APIRouter(tags=["capture"])


def _whisper_view(engine: Any, pending: Any) -> dict[str, Any]:
    prompt = engine.adapter.artefacts.get(pending.whisper_id) or {}
    return {"whisper_id": pending.whisper_id, "worker": pending.worker,
            "question": pending.whisper.question,
            "options": [o["id"] for o in pending.whisper.options],
            "observation": pending.observation.work_as_done or pending.observation.text,
            "candidate": {"category": pending.candidate.category,
                          "hypothesis": pending.candidate.hypothesis},
            "submitted_by": pending.submitted_by or pending.worker,
            "asked_at": prompt.get("produced_at")}


@router.post("/v1/workspaces/{workspace_id}/observations", status_code=status.HTTP_201_CREATED,
             summary="Report where a worker's action differed from the procedure")
def submit_observation(workspace_id: str, body: ObservationIn, p: Principal = Depends(principal),
                       repo: Any = Depends(repository)) -> dict[str, Any]:
    """A capture source may report for any worker member; a worker may report their own work.
    Metis infers a candidate (a hypothesis only) and asks the worker one whisper. Nothing is
    stored until the worker answers."""
    def capture(engine: Any) -> dict[str, Any]:
        roles = roles_in(engine, p)
        worker = body.worker or p.uri
        if Role.capture not in roles and not (Role.worker in roles and worker == p.uri):
            raise Forbidden("Reporting an observation needs the capture role, or the worker role "
                            "for your own work.")
        if Role.worker not in engine.roles_of(worker):
            raise Forbidden(f"{worker} is not a worker in {workspace_id}.")
        ctx = context_from(body.context)
        pending = engine.begin_capture(
            {"observation_id": body.observation_id, "work_as_imagined": body.work_as_imagined,
             "work_as_done": body.work_as_done, "context": ctx, "source": "api"},
            consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=worker,
            submitted_by=None if worker == p.uri else p.uri, category=body.category,
            title=body.title, conditions=ctx, supersedes=body.supersedes)
        if pending.deferred:
            return {"deferred": True, "reason": pending.deferred_reason, "worker": worker,
                    "note": "The worker has reached the whisper budget; nothing was asked."}
        return {"deferred": False, **_whisper_view(engine, pending)}
    return repo.write(workspace_id, capture)


@router.get("/v1/workspaces/{workspace_id}/whispers", summary="Whispers awaiting an answer")
def list_whispers(workspace_id: str, p: Principal = Depends(principal),
                  repo: Any = Depends(repository)) -> list[dict[str, Any]]:
    """Workers see the whispers addressed to them, and capture sources the ones they
    reported; workspace admins and auditors see all."""
    def view(engine: Any) -> list[dict[str, Any]]:
        roles = require(engine, p, Role.worker, Role.capture, Role.admin, Role.auditor,
                        global_auditor=True)
        sees_all = bool(roles & {Role.admin, Role.auditor}) or p.is_auditor
        return [_whisper_view(engine, w) for w in engine.pending_captures.values()
                if sees_all or w.worker == p.uri or w.submitted_by == p.uri]
    return repo.read(workspace_id, view)


@router.post("/v1/workspaces/{workspace_id}/whispers/{whisper_id}/answer",
             summary="Answer a whisper addressed to you")
def answer_whisper(workspace_id: str, whisper_id: str, body: WhisperAnswerIn,
                   p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    """The worker confirms, corrects, dismisses, or defers the account in their own words, and
    grants or declines consent. A fragment is stored only on confirm or correct with consent."""
    def answer(engine: Any) -> dict[str, Any]:
        pending = engine.pending_captures.get(whisper_id)
        if pending is None:
            raise NotFound(f"No whisper {whisper_id} awaits an answer.")
        if pending.worker != p.uri:
            raise Forbidden("Only the worker who was asked may answer this whisper.")
        require(engine, p, Role.worker)
        result = engine.answer_whisper(
            whisper_id, response=body.response, answered_by=p.uri,
            corrected_content=body.corrected_text, free_text=body.free_text,
            consent_granted=body.consent == "granted")
        if result.fragment is None:
            return {"stored": False, "note": "Your answer is recorded; no fragment was stored."}
        return {"stored": True, "fragment": fragment_view(result.fragment),
                "note": "Stored in the Evidence layer. It reaches agents only after a quorum of "
                        "Mission Group reviewers promotes it."}
    return repo.write(workspace_id, answer)
