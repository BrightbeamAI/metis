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
from typing import Any

from ..identity import AuthenticationError, IdentityProviderUnavailable, Principal
from ..mcp.schema import (
    CategoryHint,
    EscalationId,
    EscalationStatus,
    MemoryContext,
    MemoryListing,
    ObservationId,
    ObservedSituation,
    RequesterRole,
    RetrievalResult,
    ServerObservationResult,
    ServerWorker,
    Situation,
    TaskName,
    Title,
    WorkAsDone,
    WorkAsImagined,
    Workspace,
    WorkspaceDetails,
    WorkspaceList,
    server_options,
)
from ..storage.repository import WorkspaceBusy, WorkspaceConflict
from ..taxonomy.categories import CATEGORY_META
from . import operations as ops
from .access import ScopedRepository

log = logging.getLogger("metis.server")

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

    server = Server("metis", instructions=INSTRUCTIONS, **server_options(Server))

    def tool(name: str, title: str, description: str, *, read_only: bool,
             idempotent: bool) -> Any:
        return server.tool(name=name, title=title, description=description,
                           annotations=ToolAnnotations(
                               title=title, readOnlyHint=read_only, destructiveHint=False,
                               idempotentHint=idempotent, openWorldHint=False))

    @tool("list_workspaces", "List your workspaces",
          "List the Metis workspaces you belong to, with your roles in each. Call it first: "
          "every other tool takes a workspace id from here, and your roles decide which tools "
          "you may use (retrieval needs the agent role, reporting observations the capture "
          "role). For one workspace's review rule, reviewers, and evidence status, use "
          "describe_workspace. An auditor sees every workspace.",
          read_only=True, idempotent=True)
    async def list_workspaces() -> WorkspaceList:
        return await _call(ops.workspaces, repo)

    @tool("describe_workspace", "Describe a workspace",
          "Describe one workspace you belong to: its review rule and reviewers, escalation "
          "handler, whisper deadline, agent-visible memory, evidence-chain head and "
          "participants, and your roles. Use it to orient yourself before retrieving or "
          "reporting. It walks every hash link to report evidence_verified. To find workspace "
          "ids, use list_workspaces; for the memory itself, use list_tacit_memory. Needs "
          "membership of the workspace.",
          read_only=True, idempotent=True)
    async def describe_workspace(workspace: Workspace) -> WorkspaceDetails:
        return await _call(ops.describe, repo, workspace)

    @tool("retrieve_guidance", "Retrieve governed guidance",
          "Retrieve the reviewed tacit guidance that applies to your current work situation, "
          "with the use constraints reviewers attached. Call it before acting on equipment, a "
          "process, or a product. For a whole task's procedures, reference facts, and past "
          "cases as well, use agent_memory_context; to see what memory exists without its text, "
          "use list_tacit_memory. A context field left out never matches a condition, so give "
          "every field you know. role is the role you act for: a fragment restricted to other "
          "roles is withheld as not authorised, while context.role is matched like any other "
          "condition. When required_human_actions lists anything, stop: a person decides, the "
          "handover opens an escalation task (escalation_task_id), and check_escalation reports "
          "the decision. Needs the agent role. Each call records the decision on the evidence "
          "chain under your identity and changes no fragment.",
          read_only=False, idempotent=False)
    async def retrieve_guidance(workspace: Workspace, context: Situation,
                                role: RequesterRole = None) -> RetrievalResult:
        return await _call(ops.retrieve, repo, workspace, dict(context), role)

    @tool("agent_memory_context", "Assemble memory for a task",
          "Assemble a task's memory in one call: the workspace's procedures (SOPs), the facts "
          "and past cases that match the context, and the governed tacit guidance that applies. "
          "Use it when starting or planning a multi-step task. For a check before a single "
          "action, use retrieve_guidance instead; calling both for one step records two "
          "decisions. Tacit guidance passes the same condition-aware gate as retrieve_guidance, "
          "and task is a label recorded with the query. When required_human_actions lists "
          "anything (an escalation, or a use constraint that calls for a person's check), stop, "
          "and follow an escalation with check_escalation. Needs the agent role. Each call "
          "records the query and the gate's decisions under your identity, may open an "
          "escalation task, and changes no fragment.",
          read_only=False, idempotent=False)
    async def agent_memory_context(workspace: Workspace, task: TaskName, context: Situation,
                                   role: RequesterRole = None) -> MemoryContext:
        return await _call(ops.agent_context, repo, workspace, task, dict(context), role)

    @tool("list_tacit_memory", "List agent-visible tacit memory",
          "List the tacit memory agents may receive in a workspace, as metadata with each "
          "item's conditions of applicability and review date, without the guidance text. Use "
          "it to see which situations memory covers and which context fields to give "
          "retrieve_guidance; call retrieve_guidance to receive the guidance itself. Only "
          "memory in use appears (promoted, consented, inside its review date), all in one "
          "call. Listing records nothing, and a listed item can still be withheld at retrieval. "
          "Needs the agent, reviewer, auditor, or admin role.",
          read_only=True, idempotent=True)
    async def list_tacit_memory(workspace: Workspace) -> MemoryListing:
        return await _call(ops.memory, repo, workspace)

    @tool("check_escalation", "Check an escalation decision",
          "Report the state of an escalation that a retrieval opened, and the person's decision "
          "once it is made. Use it after retrieve_guidance or agent_memory_context return an "
          "escalation_task_id, and leave time between checks, since a person decides. After "
          "applies, call retrieve_guidance again with the same context within the grant window "
          "(12 hours by default) to receive the guidance; after does_not_apply or "
          "refer_to_review, do not use the withheld guidance. Records nothing. Open to the "
          "agent that asked and to escalation handlers, reviewers, auditors, and admins.",
          read_only=True, idempotent=True)
    async def check_escalation(workspace: Workspace, task_id: EscalationId) -> EscalationStatus:
        return await _call(ops.escalation, repo, workspace, task_id)

    @tool("submit_observation", "Report a divergence from procedure",
          "Report where a worker's action differed from the written procedure, so Metis asks "
          "that worker one short question (a whisper) in their inbox. Use it when you see or "
          "are told that work was done differently from the SOP; the worker answers in the "
          "Metis web app, or in Slack or Teams where set up, so no tool here answers it. Metis "
          "infers a candidate account (a hypothesis) and stores no fragment until the worker "
          "answers. A worker gets at most five whispers in eight hours by default; past that "
          "budget the call returns deferred, asks nothing, and spends the id. A retry with the "
          "same observation_id, worker, and work_as_done returns the whisper while it awaits an "
          "answer; any other report under a used id is refused. Needs the capture role, or the "
          "worker role to report your own work; list_workspaces shows your roles.",
          read_only=False, idempotent=True)
    async def submit_observation(
            workspace: Workspace, observation_id: ObservationId, work_as_done: WorkAsDone,
            context: ObservedSituation, worker: ServerWorker = None,
            work_as_imagined: WorkAsImagined = None, category: CategoryHint = None,
            title: Title = None) -> ServerObservationResult:
        return await _call(ops.submit_observation, repo, workspace,
                           observation_id=observation_id, work_as_done=work_as_done,
                           context=dict(context), worker=worker,
                           work_as_imagined=work_as_imagined, category=category, title=title)

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
