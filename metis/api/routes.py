"""FastAPI routes over the same engine, models, and evidence logic as the CLI.

Optional component (install with the ``api`` extra). This is a single-user reference server
for local exploration: it has no authentication and records whatever identities callers
supply, so it binds to localhost by default (``uvicorn metis.api.server:app``). Production
deployments must put authenticated reviewer and worker identities in front of it. Review
outcomes come only from callers; local model output stays advisory.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..conditions.context import TacitContext
from ..consent.model import ConsentRecord, ConsentStatus
from ..consent.revocation import RevocationReason
from ..engine import MetisEngine
from ..models.model_config import project_home
from ..scenarios import MANUFACTURING, run_spec

router = APIRouter()

# One live engine, created on the first request and seeded with the manufacturing scenario
# so the API serves data immediately. It uses real time. Importing this module does no work.
# FastAPI runs handlers on a thread pool, so every handler holds the lock while it touches
# the engine.
_engine: MetisEngine | None = None
_lock = threading.RLock()

_PROMOTIONS = ("promoted_to_advisory", "promoted_to_controlled")


def _new_engine() -> MetisEngine:
    engine = MetisEngine(workspace_id=MANUFACTURING.workspace_id, name=MANUFACTURING.name,
                         deterministic=False, site=MANUFACTURING.site)
    return run_spec(MANUFACTURING, engine=engine).engine


@contextmanager
def engine_session() -> Iterator[MetisEngine]:
    global _engine
    with _lock:
        if _engine is None:
            _engine = _new_engine()
        yield _engine


def reset_engine(engine: MetisEngine | None = None) -> None:
    global _engine
    with _lock:
        _engine = engine


class CaptureRequest(BaseModel):
    observation_id: str
    work_as_imagined: str | None = None
    work_as_done: str | None = None
    text: str | None = None
    context: dict[str, Any] = {}
    category: str | None = None
    response: str = "confirm"
    corrected_content: str | None = None
    title: str | None = None


class ReviewRequest(BaseModel):
    fragment_id: str
    outcome: str
    summary: str = ""
    change_control: dict[str, Any] | None = None
    decided_by: list[str] | None = None


class ContextRequest(BaseModel):
    context: dict[str, Any]
    role: str | None = None
    task_id: str = "tsk_api_query"


class RevokeRequest(BaseModel):
    fragment_id: str
    reason: str = "retired"
    by: str = "human:reviewer@plant_a"


@router.get("/workspace")
def get_workspace() -> dict[str, Any]:
    with engine_session() as eng:
        return eng.adapter.descriptor()


@router.get("/fragments")
def list_fragments() -> list[dict[str, Any]]:
    with engine_session() as eng:
        return [f.model_dump(mode="json") for f in eng.fragments.all()]


@router.get("/fragments/{fragment_id}")
def get_fragment(fragment_id: str) -> dict[str, Any]:
    with engine_session() as eng:
        frag = eng.fragments.get(fragment_id)
        if not frag:
            raise HTTPException(404, "fragment not found")
        return frag.model_dump(mode="json")


@router.get("/memory")
def list_memory() -> list[dict[str, Any]]:
    with engine_session() as eng:
        return [m.model_dump(mode="json") for m in eng.tacit_store.all()]


@router.get("/memory/{memory_id}")
def get_memory(memory_id: str) -> dict[str, Any]:
    with engine_session() as eng:
        m = eng.tacit_store.get(memory_id)
        if not m:
            raise HTTPException(404, "memory object not found")
        return m.model_dump(mode="json")


@router.post("/memory/query")
def memory_query(req: ContextRequest) -> dict[str, Any]:
    with engine_session() as eng:
        amc = eng.agent_context(req.task_id, TacitContext.model_validate(req.context),
                                role=req.role, emit=True)
        return amc.model_dump(mode="json")


@router.post("/capture")
def capture(req: CaptureRequest) -> dict[str, Any]:
    consent = ConsentRecord(consent_status=ConsentStatus.granted)
    with engine_session() as eng:
        result = eng.capture_observation(
            dict(observation_id=req.observation_id, work_as_imagined=req.work_as_imagined,
                 work_as_done=req.work_as_done, text=req.text,
                 context=TacitContext.model_validate(req.context), source="api"),
            consent=consent, response=req.response, corrected_content=req.corrected_content,
            category=req.category, title=req.title,
            conditions=TacitContext.model_validate(req.context))
        return {"fragment": result.fragment.model_dump(mode="json") if result.fragment else None,
                "task_id": result.task_id,
                "model_assist_records": [a.assist_id for a in result.model_assist_records]}


@router.post("/review")
def review(req: ReviewRequest) -> dict[str, Any]:
    with engine_session() as eng:
        try:
            out = eng.tier2_review(req.fragment_id, req.outcome, summary=req.summary,
                                   change_control=req.change_control, decided_by=req.decided_by)
        except (PermissionError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        memory = out.get("memory")
        return {"outcome": req.outcome, "memory_id": memory.memory_id if memory else None}


@router.post("/promote")
def promote(req: ReviewRequest) -> dict[str, Any]:
    if req.outcome not in _PROMOTIONS:
        raise HTTPException(422, f"/promote accepts only {', '.join(_PROMOTIONS)}; "
                                 "use /review for other outcomes")
    return review(req)


@router.post("/retrieve")
def retrieve(req: ContextRequest) -> dict[str, Any]:
    with engine_session() as eng:
        decision = eng.retrieve(TacitContext.model_validate(req.context), role=req.role)
        return decision.model_dump(mode="json")


@router.post("/revoke")
def revoke(req: RevokeRequest) -> dict[str, Any]:
    with engine_session() as eng:
        try:
            art = eng.governance.revoke(req.fragment_id, reason=RevocationReason(req.reason),
                                        by=req.by)
        except (PermissionError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"revocation_record_artefact": art}


@router.get("/audit")
def audit() -> list[dict[str, Any]]:
    with engine_session() as eng:
        return eng.adapter.evidence_records()


@router.post("/audit/export")
def audit_export(out: str = "evidence.jsonl") -> dict[str, Any]:
    # A plain filename only: exports always land in the project's exports directory, so a
    # request can never choose where on disk the server writes.
    if Path(out).name != out or not out.endswith(".jsonl") or out.startswith("."):
        raise HTTPException(422, "out must be a plain .jsonl filename")
    target = project_home() / "exports" / out
    target.parent.mkdir(parents=True, exist_ok=True)
    with engine_session() as eng:
        n = eng.export_audit(str(target))
        return {"exported": n, "path": str(target), "verified": eng.verify().ok}


@router.get("/model/status")
def model_status() -> dict[str, Any]:
    with engine_session() as eng:
        c = eng.model_client
        return {"provider": c.config.provider, "model": c.config.name, "url": c.config.url,
                "available": c.available()}


@router.post("/model/run")
def model_run(prompt: str, purpose: str = "draft_whisper") -> dict[str, Any]:
    with engine_session() as eng:
        res = eng.model_client.run(purpose, prompt)
        return {"used_live_model": res.used_live_model, "output": res.json(),
                "note": "advisory draft only; people make governance decisions"}
