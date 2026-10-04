"""Answers from chat tools: Slack interactions and Teams bot activities.

These endpoints authenticate their callers themselves: Slack signs each request with the app's
signing secret, and the Bot Framework sends a token Metis verifies. They answer 404 when the
integration is not configured.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

router = APIRouter(include_in_schema=False)


def _reply(status: int, body: dict[str, Any] | None) -> Response:
    return JSONResponse(body, status_code=status) if body is not None else Response(status_code=status)


@router.post("/integrations/slack/interactions")
async def slack_interactions(request: Request) -> Response:
    handler = getattr(request.app.state, "slack", None)
    if handler is None:
        return Response(status_code=404)
    body = await request.body()
    status, payload = await run_in_threadpool(handler.handle, dict(request.headers), body)
    return _reply(status, payload)


@router.post("/integrations/teams/messages")
async def teams_messages(request: Request) -> Response:
    handler = getattr(request.app.state, "teams", None)
    if handler is None:
        return Response(status_code=404)
    try:
        activity = await request.json()
    except ValueError:
        return _reply(400, {"error": "The activity is not valid JSON."})
    status, payload = await run_in_threadpool(handler.handle, dict(request.headers), activity)
    return _reply(status, payload)
