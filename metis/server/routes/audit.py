"""The evidence chain: read, verify, and export (auditors and admins)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ...governance.membership import Role
from ...identity import Principal
from ..access import require
from ..deps import principal, repository

router = APIRouter(tags=["audit"])


def _auditor(engine: Any, p: Principal) -> None:
    require(engine, p, Role.auditor, Role.admin, global_auditor=True)


@router.get("/v1/workspaces/{workspace_id}/audit", summary="Evidence-chain entries")
def read_audit(workspace_id: str, offset: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=1000), p: Principal = Depends(principal),
               repo: Any = Depends(repository)) -> dict[str, Any]:
    def view(engine: Any) -> dict[str, Any]:
        _auditor(engine, p)
        records = engine.adapter.evidence_records()
        return {"total": len(records), "offset": offset,
                "entries": records[offset:offset + limit]}
    return repo.read(workspace_id, view)


@router.get("/v1/workspaces/{workspace_id}/audit/verify",
            summary="Verify the hash-linked chain and its agreement with the ledger")
def verify(workspace_id: str, p: Principal = Depends(principal),
           repo: Any = Depends(repository)) -> dict[str, Any]:
    def view(engine: Any) -> dict[str, Any]:
        _auditor(engine, p)
        result = engine.verify()
        ledger = engine.adapter.ledger
        return {"entries": result.checked, "verified": result.ok, "errors": result.errors,
                "evidence_head": engine.adapter.chain.head,
                "ledger_entries": ledger.count, "ledger_agrees": ledger.matches(engine.adapter)}
    return repo.read(workspace_id, view)


@router.get("/v1/workspaces/{workspace_id}/audit/export",
            summary="Every evidence entry as JSON Lines")
def export(workspace_id: str, p: Principal = Depends(principal),
           repo: Any = Depends(repository)) -> StreamingResponse:
    def view(engine: Any) -> list[dict[str, Any]]:
        _auditor(engine, p)
        return engine.adapter.evidence_records()
    records = repo.read(workspace_id, view)
    lines = (json.dumps(r, separators=(",", ":")) + "\n" for r in records)
    return StreamingResponse(lines, media_type="application/x-ndjson", headers={
        "Content-Disposition": f'attachment; filename="{workspace_id}-evidence.jsonl"'})
