"""The Metis server: a multi-user HTTP API over governed tacit memory.

Every identity comes from sign-in. Workspace roles decide what each caller may do, every
workspace has one writer at a time, and each request commits everything it recorded, or
nothing. Run it with ``metis server run``, or with any ASGI server through the factory
``metis.server.app:create_app``.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .. import __version__
from ..audit.ledger import LedgerMismatch
from ..identity import AuthenticationError
from ..storage.repository import (
    StorageCorruption,
    UnknownWorkspace,
    WorkspaceConflict,
    WorkspaceExists,
)
from ..validation.states import InvalidTransition
from .deps import NotFound
from .routes import ROUTERS
from .settings import ServerSettings

log = logging.getLogger("metis.server")

# A caller-supplied request id is echoed and logged only in this form.
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

DESCRIPTION = """Governed tacit memory for AI agents, for many users.

Sign in with an OIDC access token or an API key, sent as a bearer token. Your identity comes
from sign-in, and your roles in each workspace decide what you may do: workers answer their
whispers, reviewers vote on reviews, agents receive governed guidance, capture sources report
observations, escalation handlers decide escalated retrievals, and auditors read the evidence.
Every capture, review, and retrieval is recorded on the workspace's hash-linked CHAP chain."""


def _error(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


def _message(exc: BaseException) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc) or exc.__class__.__name__


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def unauthenticated(_: Request, exc: AuthenticationError) -> JSONResponse:
        return _error(401, _message(exc), {"WWW-Authenticate": "Bearer"})

    @app.exception_handler(PermissionError)
    async def forbidden(request: Request, exc: PermissionError) -> JSONResponse:
        if exc.errno is not None:  # an operating-system error, not a refused action
            log.error("%s %s failed: %s", request.method, request.url.path, exc)
            return _error(500, "The server could not access its storage.")
        return _error(403, _message(exc))

    for missing in (UnknownWorkspace, NotFound, KeyError):
        @app.exception_handler(missing)
        async def not_found(_: Request, exc: Exception) -> JSONResponse:
            return _error(404, _message(exc))

    for conflict in (InvalidTransition, WorkspaceExists, WorkspaceConflict):
        @app.exception_handler(conflict)
        async def conflicting(_: Request, exc: Exception) -> JSONResponse:
            return _error(409, _message(exc))

    @app.exception_handler(ValueError)
    async def invalid(_: Request, exc: ValueError) -> JSONResponse:
        return _error(422, _message(exc))

    for broken in (StorageCorruption, LedgerMismatch):
        @app.exception_handler(broken)
        async def corrupted(request: Request, exc: Exception) -> JSONResponse:
            log.error("stored evidence is inconsistent (%s %s): %s", request.method,
                      request.url.path, exc)
            return _error(500, "Stored evidence for this workspace is inconsistent; an "
                               f"operator must investigate before it is used. {_message(exc)}")


def create_app(settings: ServerSettings | None = None, *, repository: Any = None,
               authenticator: Any = None) -> FastAPI:
    """Build the app. Without arguments, everything is configured from ``METIS_*`` variables."""
    settings = settings or ServerSettings.from_env()
    auth = authenticator or settings.authenticator()
    if repository is None:
        from ..storage.sql import SqlRepository

        repository = SqlRepository(
            settings.database_url, cache_size=settings.engine_cache_size,
            engine_options={"use_live_model": settings.use_live_model})

    app = FastAPI(title="Metis", version=__version__, description=DESCRIPTION)
    app.state.settings = settings
    app.state.repo = repository
    app.state.auth = auth

    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_methods=["GET", "POST", "PUT"],
                           allow_headers=["Authorization", "Content-Type", "X-API-Key",
                                          "X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        given = request.headers.get("x-request-id", "")
        request_id = given if _REQUEST_ID.fullmatch(given) else uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        log.info("%s %s %s %.1fms request_id=%s", request.method, request.url.path,
                 response.status_code, (time.perf_counter() - started) * 1000, request_id)
        return response

    _install_error_handlers(app)

    @app.get("/healthz", tags=["health"], summary="The process is running")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["health"], summary="The server can reach its database")
    def readyz() -> JSONResponse:
        try:
            repository.ping()
        except Exception as exc:  # report, do not crash the probe
            log.warning("readiness check failed: %s", exc)
            return _error(503, "The database is unreachable.")
        return JSONResponse({"status": "ready"})

    for router in ROUTERS:
        app.include_router(router)
    return app
