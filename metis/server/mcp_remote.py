"""Remote MCP: the server's governed memory for MCP clients over streamable HTTP, at ``/mcp``.

Every request signs in with the same credentials as the HTTP API (an OIDC access token or an
API key as a bearer token), and each tool acts as that identity, under its roles in the
workspace it names. Agents receive governed guidance and assembled memory and follow up on
their escalations; capture sources report observations. People answer whispers, vote, and
decide escalations in the web app, so no tool here does those.

The endpoint is stateless and answers with JSON, so any replica can serve any request.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Annotated, Any

from pydantic import Field

from ..identity import AuthenticationError, IdentityProviderUnavailable, Principal
from ..limits import MAX_ID, MAX_NAME, MAX_NOTE, MAX_TEXT, MAX_URI
from ..storage.repository import WorkspaceBusy, WorkspaceConflict
from ..taxonomy.categories import CATEGORY_META
from . import operations as ops
from .access import ScopedRepository

log = logging.getLogger("metis.server")

Workspace = Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
Id = Annotated[str, Field(min_length=1, max_length=MAX_ID)]

current_principal: ContextVar[Principal | None] = ContextVar("metis_principal", default=None)

INSTRUCTIONS = (
    "Metis serves governed tacit memory: reviewed fragments of expert practice that apply only "
    "under recorded conditions. Call list_workspaces to find your workspaces. Before acting in a "
    "work situation, call retrieve_guidance with the workspace and the current context. Treat "
    "guidance as situated advice for those conditions, and honour every use constraint. When "
    "required_human_actions lists anything, stop: a person decides, and check_escalation reports "
    "the decision."
)

GOVERNANCE = """# The Metis governance contract

- Tacit fragments are partial, situated accounts of practice, open to challenge.
- A fragment reaches an agent only after the worker confirms it and a quorum of named Mission
  Group reviewers promotes it.
- Retrieval is a governance gate: guidance arrives only where its recorded conditions match,
  with its use constraints.
- High-risk situations and near misses go to a person; the agent waits for the decision.
- Agents cannot review, promote, or authorise anything.
- Every retrieval is recorded on the workspace's hash-linked CHAP chain under the agent's
  identity.
"""


def _caller() -> Principal:
    principal = current_principal.get()
    if principal is None:
        raise _tool_error()("Sign in: send an OIDC access token or an API key as a bearer token.")
    return principal


def _tool_error() -> type[Exception]:
    try:  # mcp 2.x
        from mcp.server.mcpserver.exceptions import ToolError
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp.exceptions import ToolError
    return ToolError


async def _call(fn: Any, repo: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking repository operation off the event loop, as the signed-in caller, over
    only the workspaces they belong to. A refusal (missing role, unknown workspace or fragment,
    invalid input, a conflicting state) reaches the agent as a tool error with its reason; any
    other failure as a generic error, logged with its details."""
    import anyio

    principal = _caller()
    scoped = ScopedRepository(repo, principal)
    try:
        return await anyio.to_thread.run_sync(lambda: fn(scoped, principal, *args, **kwargs))
    except PermissionError as exc:
        if exc.errno is None:  # a refused action, not an operating-system error
            raise _tool_error()(str(exc)) from exc
        log.error("MCP tool %s failed: %s", getattr(fn, "__name__", fn), exc)
        raise _tool_error()("The server could not complete the request.") from None
    except (LookupError, ValueError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
        raise _tool_error()(message) from exc
    except (WorkspaceBusy, WorkspaceConflict):
        raise _tool_error()("The workspace is busy; try again shortly.") from None
    except Exception as exc:
        log.error("MCP tool %s failed", getattr(fn, "__name__", fn), exc_info=exc)
        raise _tool_error()("The server could not complete the request.") from None


def build_server(repo: Any) -> Any:
    try:  # mcp 2.x renamed FastMCP to MCPServer
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server
    from mcp.types import ToolAnnotations

    def annotations(read_only: bool) -> ToolAnnotations:
        return ToolAnnotations(readOnlyHint=read_only, destructiveHint=False, openWorldHint=False)

    server = Server("metis", instructions=INSTRUCTIONS)

    @server.tool(name="list_workspaces", annotations=annotations(True),
                 description="The Metis workspaces you belong to, with your roles in each.")
    async def list_workspaces() -> list[dict[str, Any]]:
        return await _call(ops.workspaces, repo)

    @server.tool(name="describe_workspace", annotations=annotations(True),
                 description="Describe a workspace: its review rule, reviewers, visible memory, "
                             "evidence-chain status, and your roles.")
    async def describe_workspace(workspace: Workspace) -> dict[str, Any]:
        return await _call(ops.describe, repo, workspace)

    @server.tool(name="retrieve_guidance", annotations=annotations(False),
                 description="Ask for governed tacit guidance for the current work situation. "
                             "Returns only guidance whose recorded conditions match `context`, "
                             "with its use constraints, plus anything a person must decide. "
                             "`context` must include `risk_class` (low, moderate, high, or "
                             "critical). The decision is recorded under your identity. Needs "
                             "the agent role.")
    async def retrieve_guidance(workspace: Workspace, context: dict[str, Any],
                                role: Annotated[str, Field(max_length=MAX_NAME)] | None = None,
                                ) -> dict[str, Any]:
        return await _call(ops.retrieve, repo, workspace, context, role)

    @server.tool(name="agent_memory_context", annotations=annotations(False),
                 description="Assemble procedural, semantic, episodic, and gated tacit memory for a "
                             "task in the given context (including `risk_class`), with required "
                             "human actions. Needs the agent role.")
    async def agent_memory_context(workspace: Workspace,
                                   task: Annotated[str, Field(max_length=MAX_NOTE)],
                                   context: dict[str, Any],
                                   role: Annotated[str, Field(max_length=MAX_NAME)] | None = None,
                                   ) -> dict[str, Any]:
        return await _call(ops.agent_context, repo, workspace, task, context, role)

    @server.tool(name="list_tacit_memory", annotations=annotations(True),
                 description="List agent-visible tacit memory (identifiers, categories, conditions, "
                             "review dates). Content arrives only through retrieve_guidance.")
    async def list_tacit_memory(workspace: Workspace) -> list[dict[str, Any]]:
        return await _call(ops.memory, repo, workspace)

    @server.tool(name="check_escalation", annotations=annotations(True),
                 description="The state of an escalation you raised, and the person's decision "
                             "once it is made: applies, does_not_apply, or refer_to_review. After "
                             "applies, call retrieve_guidance again with the same context to "
                             "receive the guidance.")
    async def check_escalation(workspace: Workspace, task_id: Id) -> dict[str, Any]:
        return await _call(ops.escalation, repo, workspace, task_id)

    @server.tool(name="submit_observation", annotations=annotations(False),
                 description="Report where a worker's action differed from the procedure. Metis "
                             "infers a candidate (a hypothesis only) and asks the worker one short "
                             "question in their inbox. Nothing is stored until the worker answers. "
                             "Needs the capture role.")
    async def submit_observation(
            workspace: Workspace, observation_id: Id,
            work_as_done: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)],
            context: dict[str, Any], worker: Annotated[str, Field(max_length=MAX_URI)],
            work_as_imagined: Annotated[str, Field(max_length=MAX_TEXT)] | None = None,
            category: Annotated[str, Field(max_length=MAX_NAME)] | None = None,
            title: Annotated[str, Field(max_length=MAX_NAME)] | None = None) -> dict[str, Any]:
        return await _call(ops.submit_observation, repo, workspace,
                           observation_id=observation_id, work_as_done=work_as_done,
                           context=context, worker=worker, work_as_imagined=work_as_imagined,
                           category=category, title=title)

    @server.resource("metis://governance", name="governance", mime_type="text/markdown",
                     description="The governance contract every Metis tool enforces.")
    def governance() -> str:
        return GOVERNANCE

    @server.resource("metis://taxonomy", name="taxonomy", mime_type="application/json",
                     description="The K1 to K17 taxonomy of tacit knowledge.")
    def taxonomy() -> str:
        return json.dumps([{"category": m.category.value, "label": m.label,
                            "domain": m.domain.value, "description": m.description}
                           for m in CATEGORY_META.values()], indent=2)

    return server


def http_endpoint(server: Any) -> Any:
    """The streamable HTTP endpoint as an ASGI app: stateless, JSON responses, at ``/mcp``.

    Every request is authenticated, so the transport's own Host-header checks for local
    servers are off.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    try:
        app = server.streamable_http_app(streamable_http_path="/mcp", json_response=True,
                                         stateless_http=True, transport_security=security)
    except TypeError:  # mcp 1.x keeps these on the server's settings
        server.settings.streamable_http_path = "/mcp"
        server.settings.json_response = True
        server.settings.stateless_http = True
        server.settings.transport_security = security
        app = server.streamable_http_app()
    return next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/mcp")


class SignedIn:
    """ASGI wrapper: authenticate each request, then serve it as that principal."""

    def __init__(self, app: Any, authenticator: Any) -> None:
        self.app = app
        self.authenticator = authenticator

    @staticmethod
    async def _reply(send: Any, status: int, detail: str,
                     headers: list[tuple[bytes, bytes]]) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), *headers]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        import anyio
        from starlette.datastructures import Headers

        try:  # signing in may fetch the provider's keys: keep it off the event loop
            principal = await anyio.to_thread.run_sync(self.authenticator.authenticate,
                                                       Headers(scope=scope))
        except AuthenticationError as exc:
            await self._reply(send, 401, str(exc), [(b"www-authenticate", b"Bearer")])
            return
        except IdentityProviderUnavailable as exc:
            await self._reply(send, 503, str(exc), [(b"retry-after", b"5")])
            return
        token = current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(token)
