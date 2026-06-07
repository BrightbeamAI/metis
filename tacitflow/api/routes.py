"""FastAPI routes over the same engine, models, and evidence logic as the CLI.

Optional component (install with the ``api`` extra). Governance remains deterministic and
human-reviewed; nothing here lets a model or an agent promote or authorise a fragment.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..conditions.context import TacitContext
from ..consent.model import ConsentRecord, ConsentStatus
from ..consent.revocation import RevocationReason
from ..engine import TacitFlowEngine
from ..scenarios import run_manufacturing

router = APIRouter()

# A single in-memory engine, seeded with the manufacturing scenario for immediate data.
ENGINE = run_manufacturing().engine


def reset_engine(engine: TacitFlowEngine | None = None) -> None:
    global ENGINE
    ENGINE = engine or run_manufacturing().engine


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
    return ENGINE.adapter.descriptor()


@router.get("/fragments")
def list_fragments() -> list[dict[str, Any]]:
    return [f.model_dump(mode="json") for f in ENGINE.fragments.all()]


@router.get("/fragments/{fragment_id}")
def get_fragment(fragment_id: str) -> dict[str, Any]:
    frag = ENGINE.fragments.get(fragment_id)
    if not frag:
        raise HTTPException(404, "fragment not found")
    return frag.model_dump(mode="json")


@router.get("/memory")
def list_memory() -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") for m in ENGINE.tacit_store.all()]


@router.get("/memory/{memory_id}")
def get_memory(memory_id: str) -> dict[str, Any]:
    m = ENGINE.tacit_store.get(memory_id)
    if not m:
        raise HTTPException(404, "memory object not found")
    return m.model_dump(mode="json")


@router.post("/memory/query")
def memory_query(req: ContextRequest) -> dict[str, Any]:
    amc = ENGINE.agent_context(req.task_id, TacitContext.model_validate(req.context), role=req.role, emit=True)
    return amc.model_dump(mode="json")


@router.post("/capture")
def capture(req: CaptureRequest) -> dict[str, Any]:
    consent = ConsentRecord(consent_status=ConsentStatus.granted)
    result = ENGINE.capture_observation(
        dict(observation_id=req.observation_id, work_as_imagined=req.work_as_imagined,
             work_as_done=req.work_as_done, text=req.text,
             context=TacitContext.model_validate(req.context), source="api"),
        consent=consent, response=req.response, corrected_content=req.corrected_content,
        category=req.category, title=req.title,
        conditions=TacitContext.model_validate(req.context))
    return {"fragment": result.fragment.model_dump(mode="json") if result.fragment else None,
            "task_id": result.task_id,
            "model_assist_records": [a.assist_id for a in result.model_assist_records]}


@router.post("/confirm")
def confirm(req: CaptureRequest) -> dict[str, Any]:
    """Confirmation is captured as part of the loop; this is an alias for /capture."""
    return capture(req)


@router.post("/review")
def review(req: ReviewRequest) -> dict[str, Any]:
    out = ENGINE.tier2_review(req.fragment_id, req.outcome, summary=req.summary,
                              change_control=req.change_control)
    return {"outcome": req.outcome, "memory_id": out.get("memory").memory_id if out.get("memory") else None}


@router.post("/promote")
def promote(req: ReviewRequest) -> dict[str, Any]:
    if req.outcome not in ("promoted_to_advisory", "promoted_to_controlled"):
        req.outcome = "promoted_to_advisory"
    return review(req)


@router.post("/retrieve")
def retrieve(req: ContextRequest) -> dict[str, Any]:
    decision = ENGINE.retrieve(TacitContext.model_validate(req.context), role=req.role)
    return decision.model_dump(mode="json")


@router.post("/revoke")
def revoke(req: RevokeRequest) -> dict[str, Any]:
    art = ENGINE.governance.revoke(req.fragment_id, reason=RevocationReason(req.reason), by=req.by)
    return {"revocation_record_artefact": art}


@router.get("/audit")
def audit() -> list[dict[str, Any]]:
    return ENGINE.adapter.evidence_records()


@router.post("/audit/export")
def audit_export(out: str = "evidence.jsonl") -> dict[str, Any]:
    n = ENGINE.export_audit(out)
    return {"exported": n, "path": out, "verified": ENGINE.verify().ok}


@router.get("/model/status")
def model_status() -> dict[str, Any]:
    c = ENGINE.model_client
    return {"provider": c.config.provider, "model": c.config.name, "url": c.config.url,
            "available": c.available()}


@router.post("/model/run")
def model_run(prompt: str, purpose: str = "draft_whisper") -> dict[str, Any]:
    res = ENGINE.model_client.run(purpose, prompt)
    return {"used_live_model": res.used_live_model, "output": res.json(),
            "note": "advisory draft only; not a governance decision"}
