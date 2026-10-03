"""The Metis MCP server over stdio. Run it with ``metis mcp``.

Each tool is a thin wrapper over ``metis.mcp.tools.MetisTools``, which holds the governance
contract. Logs go to stderr: on the stdio transport, stdout carries the protocol.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
from mcp.types import ToolAnnotations

from ..project import Project
from ..scenarios import SPECS, run_spec
from .tools import INSTRUCTIONS, MetisTools

GOVERNANCE = """# The Metis governance contract

- Tacit fragments are partial, situated accounts of practice, open to challenge.
- A fragment reaches an agent only after Tier-1 confirmation by the worker and Tier-2
  promotion by a quorum of named Mission Group reviewers.
- Retrieval is a governance gate. It checks revocation, consent, source pathway, authority
  layer, validation state, review date, role, conditions and exclusions, exact matching for
  Controlled fragments, and risk, in that order.
- High-risk situations and near misses (same equipment, different situation) go to a person.
- Agents cannot review, promote, or authorise anything. Workers answer their own whispers and
  may contest or withdraw their fragments at any time.
- Every capture, review, and retrieval decision is recorded on a hash-linked CHAP chain.
"""


def _annotations(*, read_only: bool) -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=read_only, destructiveHint=False, openWorldHint=False)


def build_server(tools: MetisTools) -> Any:
    server = _Server("metis", instructions=INSTRUCTIONS)

    @server.tool(name="retrieve_guidance", annotations=_annotations(read_only=False),
                 description="Ask for governed tacit guidance for the current work situation. "
                             "Returns only guidance whose recorded conditions match `context`, "
                             "with its use constraints, plus anything a person must decide. "
                             "The decision is recorded on the audit chain.")
    def retrieve_guidance(context: dict[str, Any], role: str | None = None) -> dict[str, Any]:
        return tools.retrieve_guidance(context, role)

    @server.tool(name="agent_memory_context", annotations=_annotations(read_only=False),
                 description="Assemble procedural, semantic, episodic, and gated tacit memory for "
                             "a task in the given context, with required human actions.")
    def agent_memory_context(task: str, context: dict[str, Any],
                             role: str | None = None) -> dict[str, Any]:
        return tools.agent_memory_context(task, context, role)

    @server.tool(name="list_tacit_memory", annotations=_annotations(read_only=True),
                 description="List agent-visible tacit memory (identifiers, categories, conditions, "
                             "review dates). Content is returned only by retrieve_guidance.")
    def list_tacit_memory() -> list[dict[str, Any]]:
        return tools.list_tacit_memory()

    @server.tool(name="describe_workspace", annotations=_annotations(read_only=True),
                 description="Describe the Metis workspace: fragments by authority layer, pending "
                             "whispers, Mission Group reviewers, and evidence-chain status.")
    def describe_workspace() -> dict[str, Any]:
        return tools.describe_workspace()

    @server.tool(name="submit_observation", annotations=_annotations(read_only=False),
                 description="Report where a worker's action diverged from the procedure. Metis "
                             "infers a candidate (a hypothesis only) and returns one short question "
                             "for the worker. Nothing is stored until the worker answers.")
    def submit_observation(observation_id: str, work_as_done: str, context: dict[str, Any],
                           worker: str, work_as_imagined: str | None = None,
                           category: str | None = None, title: str | None = None) -> dict[str, Any]:
        return tools.submit_observation(observation_id, work_as_done, context, worker,
                                        work_as_imagined, category, title)

    @server.tool(name="list_pending_whispers", annotations=_annotations(read_only=True),
                 description="List whispers waiting for a worker's answer, optionally for one worker.")
    def list_pending_whispers(worker: str | None = None) -> list[dict[str, Any]]:
        return tools.list_pending_whispers(worker)

    @server.tool(name="answer_whisper", annotations=_annotations(read_only=False),
                 description="Relay a worker's own answer to a whisper: response is confirm, "
                             "correct, dismiss, or defer, and consent is granted or declined, as "
                             "the worker stated. Never answer on the worker's behalf.")
    def answer_whisper(whisper_id: str, response: str, answered_by: str, consent: str,
                       corrected_text: str | None = None) -> dict[str, Any]:
        return tools.answer_whisper(whisper_id, response, answered_by, consent, corrected_text)

    @server.tool(name="contest_fragment", annotations=_annotations(read_only=False),
                 description="Relay a worker's or reviewer's contest of a fragment: challenge, "
                             "correct, withdraw, or request_re_elicitation. Contests open a review "
                             "or revoke a fragment; promotion stays with the Mission Group.")
    def contest_fragment(fragment_id: str, action: str, raised_by: str, rationale: str,
                         proposed_correction: str | None = None) -> dict[str, Any]:
        return tools.contest_fragment(fragment_id, action, raised_by, rationale, proposed_correction)

    @server.tool(name="audit_verify", annotations=_annotations(read_only=True),
                 description="Verify the workspace's hash-linked evidence chain and its ledger.")
    def audit_verify() -> dict[str, Any]:
        return tools.audit_verify()

    @server.tool(name="audit_tail", annotations=_annotations(read_only=True),
                 description="The most recent evidence-chain entries (sequence, method, sender).")
    def audit_tail(limit: int = 10) -> list[dict[str, Any]]:
        return tools.audit_tail(limit)

    @server.resource("metis://taxonomy", name="taxonomy", mime_type="application/json",
                     description="The K1 to K17 taxonomy of tacit knowledge and capture modalities.")
    def taxonomy() -> str:
        return json.dumps(tools.taxonomy(), indent=2)

    @server.resource("metis://governance", name="governance", mime_type="text/markdown",
                     description="The governance contract every Metis tool enforces.")
    def governance() -> str:
        return GOVERNANCE

    return server


def seed_demo_workspace(project: Project) -> str:
    """Run the pump scenario into ``project`` so a new server has governed data to serve."""
    spec = SPECS["manufacturing-pump-vibration"]
    workspace_id = project.unique_workspace_id(spec.workspace_id)
    engine = project.create_engine(workspace_id, name=spec.name, site=spec.site)
    run_spec(spec, engine=engine)
    project.save(engine)
    return workspace_id


def serve(home: str | Path | None = None, workspace: str | None = None,
          seed_demo: bool = True) -> None:
    project = Project(home)
    if workspace is None and project.active_workspace() is None:
        if not seed_demo:
            raise SystemExit(f"No Metis workspace in {project.home}. Run `metis demo` first.")
        seeded = seed_demo_workspace(project)
        print(f"metis mcp: seeded demo workspace {seeded} in {project.home}", file=sys.stderr)
    tools = MetisTools(project, workspace)
    print(f"metis mcp: serving workspace {tools.engine.adapter.workspace_id} over stdio",
          file=sys.stderr)
    build_server(tools).run("stdio")
