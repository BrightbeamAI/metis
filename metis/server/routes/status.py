"""The server's state for operators: a JSON status and Prometheus metrics.

Both need the global ``metrics`` role (give a Prometheus scraper a ``service:`` API key with it)
or the global auditor role, and report counts only: never workspace content.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from ... import __version__
from ...identity import Principal
from ..access import Forbidden
from ..deps import principal

router = APIRouter(tags=["status"])


def _status(request: Request, p: Principal) -> dict[str, Any]:
    if not p.reads_metrics:
        raise Forbidden("The server's status needs the global metrics or auditor role.")
    repo = request.app.state.repo
    counts = repo.outbox_counts()
    oldest = None
    first = repo.outbox_oldest_pending()
    if first:
        when = _dt.datetime.fromisoformat(first.replace("Z", "+00:00"))
        oldest = int((_dt.datetime.now(_dt.timezone.utc) - when).total_seconds())
    return {"version": __version__,
            "schema_version": repo.check_schema(),
            "workspaces": len(repo.list()),
            "outbox": {s: counts.get(s, 0) for s in ("pending", "sending", "delivered", "failed")},
            "oldest_pending_notification_seconds": oldest}


@router.get("/v1/admin/status", summary="Counts an operator watches (global metrics or auditor)")
def status(request: Request, p: Principal = Depends(principal)) -> dict[str, Any]:
    return _status(request, p)


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request, p: Principal = Depends(principal)) -> PlainTextResponse:
    """The same counts in the Prometheus text format."""
    s = _status(request, p)
    lines = ["# HELP metis_info The Metis server's version.", "# TYPE metis_info gauge",
             f'metis_info{{version="{s["version"]}"}} 1',
             "# HELP metis_workspaces Workspaces on this server.", "# TYPE metis_workspaces gauge",
             f"metis_workspaces {s['workspaces']}",
             "# HELP metis_outbox_notifications Notifications in the outbox, by status.",
             "# TYPE metis_outbox_notifications gauge"]
    lines += [f'metis_outbox_notifications{{status="{k}"}} {v}' for k, v in s["outbox"].items()]
    lines += ["# HELP metis_outbox_oldest_pending_seconds Age of the oldest notification "
              "awaiting delivery.", "# TYPE metis_outbox_oldest_pending_seconds gauge",
              f"metis_outbox_oldest_pending_seconds {s['oldest_pending_notification_seconds'] or 0}"]
    return PlainTextResponse("\n".join(lines) + "\n",
                             media_type="text/plain; version=0.0.4; charset=utf-8")
