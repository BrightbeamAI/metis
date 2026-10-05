"""The Metis MCP server over stdio. Run it with ``metis mcp``.

Each tool is a thin wrapper over ``metis.mcp.tools.MetisTools``, which holds the governance
contract, and ``metis.mcp.schema`` documents what each tool takes and returns. Logs go to
stderr: on the stdio transport, stdout carries the protocol.
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
from .schema import (
    AnsweredBy,
    AnswerResult,
    CategoryHint,
    ChainCheck,
    ChainTail,
    Consent,
    ContestActionName,
    ContestResult,
    CorrectedText,
    Correction,
    FragmentId,
    MemoryContext,
    MemoryListing,
    ObservationId,
    ObservationResult,
    ObservedSituation,
    PendingWhispers,
    RaisedBy,
    Rationale,
    RequesterRole,
    Response,
    RetrievalResult,
    Situation,
    TailLimit,
    TaskName,
    Title,
    WhisperId,
    WorkAsDone,
    WorkAsImagined,
    Worker,
    WorkerFilter,
    WorkspaceSummary,
    server_options,
)
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


def _hints(title: str, *, read_only: bool, idempotent: bool,
           destructive: bool = False) -> ToolAnnotations:
    return ToolAnnotations(title=title, readOnlyHint=read_only, destructiveHint=destructive,
                           idempotentHint=idempotent, openWorldHint=False)


def build_server(tools: MetisTools) -> Any:
    server = _Server("metis", instructions=INSTRUCTIONS, **server_options(_Server))

    def tool(name: str, title: str, description: str, **hints: bool) -> Any:
        return server.tool(name=name, title=title, description=description,
                           annotations=_hints(title, **hints))

    @tool("retrieve_guidance", "Retrieve governed guidance",
          "Retrieve the reviewed tacit guidance that applies to the current work situation, "
          "with the use constraints reviewers attached. Call it before acting on equipment, a "
          "process, or a product. For a whole task's procedures, reference facts, and past "
          "cases as well, use agent_memory_context; to see what memory exists without its text, "
          "use list_tacit_memory. A context field left out never matches a condition, so give "
          "every field you know. role is the role you act for: a fragment restricted to other "
          "roles is withheld as not authorised, while context.role is matched like any other "
          "condition. When required_human_actions lists anything, stop and hand the decision to "
          "a person: high and critical risk and near misses (the same equipment in a different "
          "situation) always need one, and the handover opens an escalation task "
          "(escalation_task_id). Each call records the decision on the workspace's evidence "
          "chain and changes no fragment.",
          read_only=False, idempotent=False)
    def retrieve_guidance(context: Situation, role: RequesterRole = None) -> RetrievalResult:
        return tools.retrieve_guidance(dict(context), role)

    @tool("agent_memory_context", "Assemble memory for a task",
          "Assemble a task's memory in one call: the workspace's procedures (SOPs), the facts "
          "and past cases that match the context, and the governed tacit guidance that applies. "
          "Use it when starting or planning a multi-step task. For a check before a single "
          "action, use retrieve_guidance instead; calling both for one step records two "
          "decisions. Tacit guidance passes the same condition-aware gate as retrieve_guidance, "
          "and task is a label recorded with the query. When required_human_actions lists "
          "anything (an escalation, or a use constraint that calls for a person's check), stop "
          "and hand the decision to a person. Each call records the query and the gate's "
          "decisions on the evidence chain, may open an escalation task, and changes no "
          "fragment.",
          read_only=False, idempotent=False)
    def agent_memory_context(task: TaskName, context: Situation,
                             role: RequesterRole = None) -> MemoryContext:
        return tools.agent_memory_context(task, dict(context), role)

    @tool("list_tacit_memory", "List agent-visible tacit memory",
          "List the tacit memory agents may receive in this workspace, as metadata with each "
          "item's conditions of applicability and review date, without the guidance text. Use "
          "it to see which situations memory covers and which context fields to give "
          "retrieve_guidance; call retrieve_guidance to receive the guidance itself. Only "
          "memory in use appears (promoted, consented, inside its review date), all in one "
          "call. Listing records nothing, and a listed item can still be withheld at retrieval "
          "when the situation, role, or risk class does not allow it.",
          read_only=True, idempotent=True)
    def list_tacit_memory() -> MemoryListing:
        return tools.list_tacit_memory()

    @tool("describe_workspace", "Describe the workspace",
          "Summarise the workspace this server serves: fragments per authority layer, "
          "agent-visible memory, pending whispers, Mission Group reviewers and their review "
          "rule, and whether the evidence chain verifies. Use it to orient yourself at the "
          "start of a session. It walks every hash link to report verified; for the ledger "
          "comparison and the errors found, use audit_verify, and for the memory itself, "
          "list_tacit_memory.",
          read_only=True, idempotent=True)
    def describe_workspace() -> WorkspaceSummary:
        return tools.describe_workspace()

    @tool("submit_observation", "Report a divergence from procedure",
          "Report where a worker's action differed from the written procedure; Metis drafts one "
          "short question (a whisper) for you to put to that worker. Use it when you see or are "
          "told that work was done differently from the SOP, and relay the worker's reply with "
          "answer_whisper; to dispute a stored fragment, use contest_fragment. Metis infers a "
          "candidate account (a hypothesis) and stores no fragment until the worker answers. A "
          "worker gets at most five whispers in eight hours by default; past that budget the "
          "call returns deferred, asks nothing, and spends the id, so report it again later "
          "under a new observation_id. A retry with the same observation_id, worker, and "
          "work_as_done returns the whisper while it awaits an answer; any other report under a "
          "used id is refused. Identities are not verified here, so give the worker's real URI.",
          read_only=False, idempotent=True)
    def submit_observation(observation_id: ObservationId, work_as_done: WorkAsDone,
                           context: ObservedSituation, worker: Worker,
                           work_as_imagined: WorkAsImagined = None,
                           category: CategoryHint = None, title: Title = None) -> ObservationResult:
        return tools.submit_observation(observation_id, work_as_done, dict(context), worker,
                                        work_as_imagined, category, title)

    @tool("list_pending_whispers", "List whispers awaiting an answer",
          "List the whispers still waiting for a worker's answer, oldest first, in one call. "
          "Use it to recover a whisper_id before relaying an answer with answer_whisper; "
          "submit_observation already returns the whisper_id, so call this only when you no "
          "longer have it. A whisper leaves the list once answered, and a deferred observation "
          "never appears because it raised none. worker filters by the exact URI given to "
          "submit_observation.",
          read_only=True, idempotent=True)
    def list_pending_whispers(worker: WorkerFilter = None) -> PendingWhispers:
        return tools.list_pending_whispers(worker)

    @tool("answer_whisper", "Relay a worker's answer to a whisper",
          "Relay a worker's own answer to a whisper, with the consent they stated. Use it only "
          "with the choice and words of the worker the whisper is addressed to, never with your "
          "own judgement. To start a capture, use submit_observation; to dispute a stored "
          "fragment, use contest_fragment. A fragment is stored only for confirm, or correct "
          "with the worker's corrected_text, given with consent granted: it enters the Evidence "
          "layer and reaches agents only after a quorum of Mission Group reviewers promotes it. "
          "Any other answer is recorded and stores nothing. Every answer, defer included, "
          "closes the whisper, and a second answer or one from anyone but its addressee is "
          "refused.",
          read_only=False, idempotent=False)
    def answer_whisper(whisper_id: WhisperId, response: Response, answered_by: AnsweredBy,
                       consent: Consent, corrected_text: CorrectedText = None) -> AnswerResult:
        return tools.answer_whisper(whisper_id, response, answered_by, consent, corrected_text)

    @tool("contest_fragment", "Relay a contest of a fragment",
          "Relay a person's contest of a stored fragment: challenge it, correct it, supersede "
          "it, withdraw it, or ask the worker to give the account again. Use it when a worker "
          "or reviewer says a fragment is wrong or outdated, or its contributor takes it back; "
          "to answer a pending whisper, use answer_whisper. Only the fragment's contributor may "
          "withdraw it, which revokes it at once and for good: it leaves agent-visible memory, "
          "and its history stays on the evidence chain. Every other action opens or joins a "
          "Mission Group review, and the fragment stays in use until the reviewers decide; a "
          "fragment already out of review keeps the contest on record.",
          read_only=False, idempotent=False, destructive=True)
    def contest_fragment(fragment_id: FragmentId, action: ContestActionName, raised_by: RaisedBy,
                         rationale: Rationale,
                         proposed_correction: Correction = None) -> ContestResult:
        return tools.contest_fragment(fragment_id, action, raised_by, rationale,
                                      proposed_correction)

    @tool("audit_verify", "Verify the evidence chain",
          "Verify the workspace's whole hash-linked evidence chain and, when the workspace "
          "keeps an append-only ledger, check that the ledger agrees entry for entry. Use it "
          "before relying on the record, or after an incident. For the verified flag alone, use "
          "describe_workspace; to list recent entries, use audit_tail. A failed check is a "
          "normal result, verified false with the errors found, and the check reads every "
          "entry, so it takes longer as the chain grows.",
          read_only=True, idempotent=True)
    def audit_verify() -> ChainCheck:
        return tools.audit_verify()

    @tool("audit_tail", "Read the latest evidence-chain entries",
          "Read the latest entries on the workspace's evidence chain, newest last: each gives "
          "its sequence number, method, and sender, without its content. Use it to confirm what "
          "was recorded; retrieve_guidance's recorded_at_seq appears here as an entry's seq. "
          "Raise limit to look further back; with no offset, the latest 200 entries are as far "
          "as this tool reaches. To check the chain's integrity, use audit_verify.",
          read_only=True, idempotent=True)
    def audit_tail(limit: TailLimit = 10) -> ChainTail:
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
