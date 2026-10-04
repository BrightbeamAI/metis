"""Ingesting records from workplace systems through configured source mappings."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from ...identity import Principal
from .. import operations as ops
from ..deps import NotFound, principal, repository

router = APIRouter(tags=["connectors"])


@router.get("/v1/connectors", summary="The configured sources records can come from")
def sources(request: Request, p: Principal = Depends(principal)) -> list[dict[str, Any]]:
    return [{"source": name, "records": m.records, "filter": m.when}
            for name, m in sorted(request.app.state.connectors.items())]


@router.post("/v1/workspaces/{workspace_id}/ingest/{source}",
             summary="Capture observations from a source's records (capture)")
def ingest(workspace_id: str, source: str, request: Request, payload: Any = Body(...),
           p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    """Send a source's records as they are: one record, a list, or the payload the source
    sends, with the records where the mapping's ``records`` path says. Each record that passes
    the mapping's filter becomes an observation for its worker, and the worker gets a whisper.
    Records already captured are reported as duplicates."""
    mapping = request.app.state.connectors.get(source)
    if mapping is None:
        raise NotFound(f"No source mapping named {source}; configure METIS_CONNECTORS_FILE.")
    return ops.ingest(repo, p, workspace_id, mapping, mapping.records_in(payload))
