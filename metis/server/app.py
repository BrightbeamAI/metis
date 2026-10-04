"""The Metis server: a multi-user HTTP API over governed tacit memory.

Every identity comes from sign-in. Workspace roles decide what each caller may do, every
workspace has one writer at a time, and each request commits everything it recorded, or
nothing. Run it with ``metis server run``, or with any ASGI server through the factory
``metis.server.app:create_app``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .. import __version__
from ..audit.ledger import LedgerMismatch
from ..identity import AuthenticationError, IdentityProviderUnavailable
from ..storage.repository import (
    SchemaTooNew,
    StorageCorruption,
    UnknownWorkspace,
    WorkspaceBusy,
    WorkspaceConflict,
    WorkspaceExists,
)
from ..validation.states import InvalidTransition
from .deps import NotFound
from .factory import build_repository, chat_integrations, connect_directories
from .routes import ROUTERS
from .settings import ServerSettings

log = logging.getLogger("metis.server")

# A caller-supplied request id is echoed and logged only in this form.
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

DESCRIPTION = """Governed tacit memory for AI agents, for many users.

Sign in with an OIDC access token or an API key, sent as a bearer token. Your identity comes
from sign-in, and your roles in each workspace decide what you may do: workers answer their
whispers, reviewers vote on reviews, agents receive governed guidance, capture sources report
observations, escalation handlers decide escalated retrievals, and auditors read the evidence.
Every capture, review, and retrieval is recorded on the workspace's hash-linked CHAP chain."""


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def _error(status: int, detail: str, headers: dict[str, str] | None = None,
           request: Request | None = None) -> JSONResponse:
    body: dict[str, Any] = {"detail": detail}
    if request is not None and status >= 500:
        body["request_id"] = _request_id(request)
    return JSONResponse(body, status_code=status, headers=headers)


def _message(exc: BaseException) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc) or exc.__class__.__name__


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def unauthenticated(_: Request, exc: AuthenticationError) -> JSONResponse:
        return _error(401, _message(exc), {"WWW-Authenticate": "Bearer"})

    @app.exception_handler(IdentityProviderUnavailable)
    async def provider_down(request: Request, exc: IdentityProviderUnavailable) -> JSONResponse:
        return _error(503, _message(exc), {"Retry-After": "5"}, request)

    @app.exception_handler(WorkspaceBusy)
    async def busy(request: Request, exc: WorkspaceBusy) -> JSONResponse:
        return _error(503, _message(exc), {"Retry-After": "2"}, request)

    @app.exception_handler(PermissionError)
    async def forbidden(request: Request, exc: PermissionError) -> JSONResponse:
        if exc.errno is not None:  # an operating-system error, not a refused action
            log.error("%s %s failed: %s request_id=%s", request.method, request.url.path, exc,
                      _request_id(request))
            return _error(500, "The server could not access its storage.", request=request)
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

    @app.exception_handler(SchemaTooNew)
    async def too_new(request: Request, exc: SchemaTooNew) -> JSONResponse:
        log.error("%s request_id=%s", exc, _request_id(request))
        return _error(500, "This workspace was written by a newer version of Metis; upgrade "
                           "this server.", request=request)

    for broken in (StorageCorruption, LedgerMismatch):
        @app.exception_handler(broken)
        async def corrupted(request: Request, exc: Exception) -> JSONResponse:
            log.error("stored evidence is inconsistent (%s %s): %s request_id=%s",
                      request.method, request.url.path, exc, _request_id(request))
            return _error(500, "Stored evidence for this workspace is inconsistent; an operator "
                               "must investigate before it is used.", request=request)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("%s %s failed request_id=%s", request.method, request.url.path,
                  _request_id(request), exc_info=exc)
        return _error(500, "The server could not complete the request.", request=request)


class BodyLimit:
    """ASGI middleware: refuse request bodies above ``max_bytes`` with 413, before anything
    reads or parses them. A body without a declared length is read here first, up to the limit,
    and handed on whole."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _refuse(self, send: Any) -> None:
        body = json.dumps({"detail": f"The request body is larger than {self.max_bytes} bytes."})
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body.encode("utf-8")})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > self.max_bytes
            except ValueError:
                too_large = True
            if too_large:
                await self._refuse(send)
                return
            await self.app(scope, receive, send)  # the server holds the body to its length
            return
        if scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        chunks, seen = [], 0
        while True:  # a body of unknown length: read it here, to the limit
            message = await receive()
            if message.get("type") != "http.request":
                chunks.append(message)
                break
            seen += len(message.get("body", b""))
            if seen > self.max_bytes:
                await self._refuse(send)
                return
            chunks.append(message)
            if not message.get("more_body", False):
                break
        body = b"".join(m.get("body", b"") for m in chunks if m.get("type") == "http.request")
        replayed = False

        async def replay() -> Any:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: ServerSettings | None = None, *, repository: Any = None,
               authenticator: Any = None) -> FastAPI:
    """Build the app. Without arguments, everything is configured from ``METIS_*`` variables."""
    settings = settings or ServerSettings.from_env()
    if not logging.getLogger().handlers:  # the process has no logging set up yet
        logging.basicConfig(level=settings.log_level.upper(),
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # The MCP SDK is chatty, and HTTP clients log each request's full URL, where webhook URLs
    # carry their secrets.
    for name in ("mcp", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    auth = authenticator or settings.authenticator()
    slack_api, teams_connector, chat_channels = chat_integrations(settings)
    owns_repository = repository is None
    if repository is None:
        repository = build_repository(settings, chat_channels=chat_channels)
    else:
        connect_directories(chat_channels, repository)

    from ..notify import Dispatcher
    from .background import Sweeper

    notifier = getattr(repository, "notifier", None)
    dispatcher = Dispatcher(repository, notifier.channels) if notifier is not None else None
    sweeper = Sweeper(repository, retention_days=settings.outbox_retention_days)
    mcp_server = _remote_mcp(repository) if settings.remote_mcp else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        if dispatcher is not None:
            dispatcher.start(settings.dispatch_interval_seconds)
        sweeper.start(settings.sweep_interval_seconds)
        try:
            if mcp_server is not None:
                async with mcp_server[0].session_manager.run():
                    yield
            else:
                yield
        finally:
            if dispatcher is not None:  # stop delivering first, then sweeping
                dispatcher.stop()
            sweeper.stop()
            if owns_repository:
                repository.close()

    app = FastAPI(title="Metis", version=__version__, description=DESCRIPTION, lifespan=lifespan,
                  docs_url="/docs" if settings.api_docs else None, redoc_url=None)
    app.state.settings = settings
    app.state.repo = repository
    app.state.auth = auth
    app.state.dispatcher = dispatcher
    app.state.sweeper = sweeper
    if settings.connectors_file:
        from ..connectors.mapping import load_mappings

        app.state.connectors = load_mappings(settings.connectors_file)
    else:
        app.state.connectors = {}
    app.state.slack = app.state.teams = None
    if slack_api is not None:
        from ..connectors.slack import SlackInteractions

        app.state.slack = SlackInteractions(repository, slack_api, settings.slack_signing_secret)
    if teams_connector is not None:
        from ..connectors.teams import TeamsBot, TeamsBotAuth

        app.state.teams = TeamsBot(repository, TeamsBotAuth(settings.teams_app_id),
                                   teams_connector, tenants=settings.teams_tenants,
                                   service_hosts=teams_connector.service_hosts)

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
        request.state.request_id = request_id
        started = time.perf_counter()
        path, root = request.scope.get("path", ""), request.scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root):]
        if (request.method in _UNSAFE and path.startswith("/v1/")
                and request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"):
            # Every change is sent as JSON. A cross-site form cannot send JSON, so credentials a
            # browser adds by itself (a proxy's cookie) cannot make changes for another site.
            response: Response = _error(415, "Send the request as JSON (Content-Type: "
                                             "application/json).")
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        log.info("%s %s %d %.1fms principal=%s request_id=%s", request.method,
                 request.url.path, int(response.status_code),
                 (time.perf_counter() - started) * 1000,
                 getattr(request.state, "principal", "-"), request_id)
        return response

    app.add_middleware(BodyLimit, max_bytes=settings.max_body_bytes)
    _install_error_handlers(app)

    @app.get("/healthz", tags=["health"], summary="The process is running")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["health"], summary="The server can reach its database")
    async def readyz() -> JSONResponse:
        try:
            await asyncio.wait_for(run_in_threadpool(repository.ping), timeout=3)
        except Exception as exc:  # report, do not crash the probe
            log.warning("readiness check failed: %s", exc or exc.__class__.__name__)
            return _error(503, "The database is unreachable.")
        return JSONResponse({"status": "ready"})

    for router in ROUTERS:
        app.include_router(router)
    if mcp_server is not None:
        from starlette.routing import Route

        from .mcp_remote import SignedIn

        # Stateless JSON over POST: there is no event stream to open (GET) or session to end.
        app.router.routes.append(Route("/mcp", endpoint=SignedIn(mcp_server[1], auth),
                                       methods=["POST"]))
    return app


def _remote_mcp(repository: Any) -> tuple[Any, Any] | None:
    """The remote MCP server and its HTTP endpoint, when the MCP SDK is installed."""
    import importlib.util

    if importlib.util.find_spec("mcp") is None:
        log.info("remote MCP is off: install the mcp extra to serve /mcp")
        return None
    from .mcp_remote import build_server, http_endpoint

    server = build_server(repository)
    return server, http_endpoint(server)
