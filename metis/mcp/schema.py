"""What the Metis MCP tools take and return, as documented types.

Both MCP surfaces, ``metis mcp`` over stdio and the server's remote ``/mcp`` endpoint, build
their tools from these types. Every tool therefore publishes a JSON Schema in which each
argument and each returned field carries its meaning, its allowed values, and the size limits
the HTTP API applies. The output types describe the governed views in ``metis.guidance`` and
the results of the tool methods, key for key. This module does not depend on the MCP SDK.
"""
import datetime as _dt
import inspect
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field
from typing_extensions import Required, TypedDict

from ..conditions.context import RISK_CLASSES
from ..consent.contestability import ContestAction
from ..limits import MAX_ID, MAX_NAME, MAX_NOTE, MAX_TEXT, MAX_URI
from ..taxonomy.categories import Category

WEBSITE = "https://metis.brightbeam.works"
SERVER_DESCRIPTION = (
    "Governed tacit memory for AI agents: reviewed fragments of expert practice that reach an "
    "agent only where their recorded conditions match, with every retrieval recorded on a "
    "hash-linked evidence chain.")


def server_options(server_class: Any) -> dict[str, Any]:
    """How the server introduces itself to clients (title, description, home page, and this
    package's version), limited to the options the installed MCP SDK accepts."""
    from .. import __version__

    wanted = {"title": "Metis", "description": SERVER_DESCRIPTION, "website_url": WEBSITE,
              "version": __version__}
    accepted = inspect.signature(server_class.__init__).parameters
    return {key: value for key, value in wanted.items() if key in accepted}


# ---- arguments --------------------------------------------------------------------------

RiskClass = Literal[RISK_CLASSES]
CategoryName = Literal[tuple(c.value for c in Category)]
Response = Annotated[Literal["confirm", "correct", "dismiss", "defer"], Field(
    description="The worker's answer: confirm (the candidate is right), correct (right with "
                "the changes in corrected_text), dismiss (not a real practice), or defer (the "
                "worker will not answer now). Each closes the whisper.")]
Consent = Annotated[Literal["granted", "declined"], Field(
    description="The worker's own decision on keeping their account: granted keeps it, "
                "declined keeps nothing. Relay what the worker said.")]
ContestActionName = Annotated[Literal[tuple(a.value for a in ContestAction)], Field(
    description="challenge (question it), correct (propose new wording), supersede (replace it "
                "with a newer account), withdraw (the contributor takes it back), or "
                "request_re_elicitation (ask the worker to give the account again).")]

# A context value: one value, or a list meaning any of its values. The context's size limits
# (``metis.limits.check_context``) are checked when it arrives.
Scalar = str | list[str]


class _SituationFields(TypedDict, total=False):
    __pydantic_config__ = ConfigDict(extra="forbid")

    site: Annotated[Scalar | None, Field(description="The site, for example plant_a.")]
    area: Annotated[Scalar | None, Field(description="The area of the site, for example utilities.")]
    line: Annotated[Scalar | None, Field(description="The production line, for example line_3.")]
    equipment_family: Annotated[Scalar | None, Field(
        description="The kind of equipment, for example centrifugal_pump.")]
    equipment_id: Annotated[Scalar | None, Field(
        description="The specific asset, for example PUMP-A.")]
    product_family: Annotated[Scalar | None, Field(
        description="The product or batch family, for example resin_batch.")]
    material_lot: Annotated[Scalar | None, Field(description="The material lot in use.")]
    operating_mode: Annotated[Scalar | None, Field(
        description="How the equipment or process is running, for example high_load, startup, "
                    "or inspection.")]
    shift_pattern: Annotated[Scalar | None, Field(description="The shift, for example night.")]
    role: Annotated[Scalar | None, Field(
        description="The role of the person doing the work, for example operator.")]
    trigger_context: Annotated[Scalar | None, Field(
        description="What prompted the question, for example pre_alarm.")]
    environmental_conditions: Annotated[
        dict[str, Scalar], Field(
            description='Other named conditions, for example {"ambient_temp": "hot"}. Each is '
                        "matched like the fields above.")]


class WorkContext(_SituationFields, total=False):
    """The work situation an agent is in. Guidance applies only where every condition it
    records matches a field here, and a field left out never matches, so give every field you
    know. A list means any of its values. Values are at most 256 characters, lists and
    mappings at most 32 entries, and the whole context at most 4096 bytes of JSON."""

    risk_class: Required[Annotated[RiskClass, Field(
        description="The risk of the situation. high and critical hand every applicable "
                    "fragment to a person instead of returning it.")]]


class ObservationContext(_SituationFields, total=False):
    """Where the observed practice happened. It becomes the candidate fragment's conditions
    of applicability, so the fragment later applies only to matching situations. A list means
    any of its values. Values are at most 256 characters, lists and mappings at most 32
    entries, and the whole context at most 4096 bytes of JSON."""

    risk_class: Annotated[RiskClass | None, Field(description="The risk of the situation.")]
    exclusion_conditions: Annotated[list[dict[str, Scalar]], Field(
        description='Situations the practice does not cover, each a partial context, for '
                    'example [{"operating_mode": "startup"}].')]
    valid_from: Annotated[_dt.datetime | None, Field(
        description="When the practice starts to apply, as an ISO 8601 time.")]
    valid_until: Annotated[_dt.datetime | None, Field(
        description="When the practice stops applying, as an ISO 8601 time.")]


DEMO_CONTEXT = {
    "site": "plant_a", "area": "utilities", "line": "line_3",
    "equipment_family": "centrifugal_pump", "equipment_id": "PUMP-A",
    "operating_mode": "high_load", "shift_pattern": "night", "trigger_context": "pre_alarm",
    "risk_class": "moderate", "role": "operator",
}

Situation = Annotated[WorkContext, Field(
    description="The current work situation, with risk_class.", examples=[DEMO_CONTEXT])]
ObservedSituation = Annotated[ObservationContext, Field(
    description="The situation the worker was in when the practice was observed.",
    examples=[{k: v for k, v in DEMO_CONTEXT.items() if k != "risk_class"}])]

Workspace = Annotated[str, Field(
    min_length=1, max_length=MAX_NAME, examples=["wsp_plant_a"],
    description="The workspace id, from list_workspaces.")]
RequesterRole = Annotated[
    Annotated[str, Field(min_length=1, max_length=MAX_NAME)] | None, Field(
        description="The role you act for, for example operator. A fragment whose conditions "
                    "name other roles is withheld with reason role_not_authorised. Omit it to "
                    "skip that check.")]
TaskName = Annotated[str, Field(
    min_length=1, max_length=MAX_NOTE, examples=["inspect PUMP-A after the pre-alarm"],
    description="A short name for the task, recorded with the query.")]
ObservationId = Annotated[str, Field(
    min_length=1, max_length=MAX_ID, examples=["WO-1042"],
    description="Your stable id for this observation, such as a work-order number. Reuse it "
                "when you retry, so the worker is asked once; a deferral or an answer spends "
                "it.")]
WorkAsDone = Annotated[str, Field(
    min_length=1, max_length=MAX_TEXT, examples=["Eased the load back when the pump note dulled."],
    description="What the worker did, in plain words, as observed or reported.")]
WorkAsImagined = Annotated[
    Annotated[str, Field(max_length=MAX_TEXT)] | None, Field(
        description="What the written procedure says should happen, when you know it.")]
_Human = Annotated[str, Field(
    min_length=1, max_length=MAX_URI, pattern=r"^human:", examples=["human:operator@plant_a"])]
Worker = Annotated[_Human, Field(
    description="The worker to ask, as their participant URI. Only a person (human:...) is "
                "asked.")]
AnsweredBy = Annotated[_Human, Field(
    description="The worker who answered: the person the whisper is addressed to.")]
RaisedBy = Annotated[_Human, Field(
    description="The person raising the contest. withdraw needs the fragment's contributor.")]
WorkerFilter = Annotated[_Human | None, Field(
    description="Show only the whispers addressed to this worker. Omit it for every worker.")]
ServerWorker = Annotated[
    Annotated[str, Field(min_length=1, max_length=MAX_URI)] | None, Field(
        examples=["human:operator@plant_a"],
        description="The worker to ask, as a participant URI with the worker role. Defaults to "
                    "you, for reporting your own work.")]
CategoryHint = Annotated[CategoryName | None, Field(
    description="The kind of tacit knowledge, from the K1 to K17 taxonomy in the "
                "metis://taxonomy resource. Metis infers one when omitted.")]
Title = Annotated[
    Annotated[str, Field(max_length=MAX_NAME)] | None, Field(
        description="A short title for the candidate fragment. Metis drafts one when omitted.")]
WhisperId = Annotated[str, Field(
    min_length=1, max_length=MAX_ID,
    description="The whisper's id, from submit_observation or list_pending_whispers.")]
FragmentId = Annotated[str, Field(
    min_length=1, max_length=MAX_ID, examples=["TF-00001"],
    description="The fragment's id, from list_tacit_memory, a retrieval, or answer_whisper.")]
EscalationId = Annotated[str, Field(
    min_length=1, max_length=MAX_ID,
    description="The escalation_task_id that retrieve_guidance or agent_memory_context "
                "returned.")]
Rationale = Annotated[str, Field(
    min_length=1, max_length=MAX_NOTE,
    description="Why, in the person's own words. It is recorded on the evidence chain.")]
Correction = Annotated[
    Annotated[str, Field(max_length=MAX_TEXT)] | None, Field(
        description="The replacement wording, for correct and supersede.")]
CorrectedText = Annotated[
    Annotated[str, Field(max_length=MAX_TEXT)] | None, Field(
        description="Required with response correct: the worker's corrected account in their "
                    "own words.")]
TailLimit = Annotated[int, Field(
    ge=1, le=200, description="How many of the latest entries to return.")]


# ---- results ----------------------------------------------------------------------------

class GuidanceItem(TypedDict):
    """One piece of guidance that passed every governance check for the situation."""

    fragment_id: Annotated[str, Field(description="The fragment the guidance comes from.")]
    memory_id: Annotated[str | None, Field(description="Its agent-visible memory object.")]
    authority_layer: Annotated[str, Field(
        description="advisory, or controlled (applies only on an exact condition match).")]
    guidance: Annotated[str, Field(
        description="The guidance: situated advice for the conditions it records.")]
    use_constraints: Annotated[list[str], Field(
        description="Constraints the reviewers attached. Honour every one.")]
    confidence: Annotated[float, Field(
        description="The fragment's evidence confidence, from 0 to 1.")]


class WithheldItem(TypedDict):
    """A fragment the gate withheld, with the reason an agent may see."""

    fragment_id: Annotated[str | None, Field(description="The withheld fragment.")]
    reason: Annotated[str, Field(
        description="The reason code, for example conditions_do_not_match or "
                    "risk_class_requires_human_escalation.")]
    explanation: Annotated[str, Field(description="The reason in plain words.")]
    detail: Annotated[str | None, Field(
        description="Specifics, such as the conditions that did not match.")]
    a_person_decides: Annotated[bool, Field(
        description="True when the gate handed the fragment to a person: a near miss or a "
                    "high-risk situation.")]


_GuidanceList = Annotated[list[GuidanceItem], Field(
    description="Guidance whose recorded conditions match the context. Empty when none "
                "applies.")]
_WithheldList = Annotated[list[WithheldItem], Field(
    description="Fragments about this situation that were withheld, with the reason.")]
_NotYetAuthorised = Annotated[int, Field(
    description="How many unreviewed or unauthorised fragments were left out. They stay "
                "unnamed until reviewers promote them.")]
_HumanActions = Annotated[list[str], Field(
    description="Decisions a person must make before you act. When any is listed, stop and "
                "hand the decision to a person.")]
_EscalationTask = Annotated[str | None, Field(
    description="The escalation opened for a person, when the gate handed anything over.")]


class RetrievalResult(TypedDict):
    """A governed retrieval: the guidance that applies, what was withheld and why, and any
    decision a person must make."""

    guidance: _GuidanceList
    withheld: _WithheldList
    not_yet_authorised: _NotYetAuthorised
    required_human_actions: _HumanActions
    escalation_task_id: _EscalationTask
    recorded_at_seq: Annotated[int, Field(
        description="The evidence-chain sequence number of the recorded decision.")]
    note: Annotated[str, Field(description="How to use the guidance.")]


class MemoryEntry(TypedDict):
    """A procedural, semantic, or episodic memory entry."""

    source: Annotated[str, Field(description="Where the entry comes from, for example SOP-17.")]
    content: Annotated[Any, Field(description="The entry as recorded.")]


class TacitItem(TypedDict):
    """Tacit guidance that passed every governance check for the task's situation."""

    memory_id: Annotated[str, Field(description="The agent-visible memory object.")]
    fragment_id: Annotated[str, Field(description="The fragment the guidance comes from.")]
    authority_layer: Annotated[str, Field(description="advisory or controlled.")]
    guidance: Annotated[str, Field(
        description="The guidance: situated advice for the conditions it records.")]
    use_constraints: Annotated[list[str], Field(
        description="Constraints the reviewers attached. Honour every one.")]


class MemoryContext(TypedDict):
    """Everything Metis holds for a task in its situation, with tacit memory gated."""

    task: Annotated[str, Field(description="The task the context was assembled for.")]
    procedural: Annotated[list[MemoryEntry], Field(
        description="The workspace's procedures, such as SOPs, all of them.")]
    semantic: Annotated[list[MemoryEntry], Field(
        description="Facts about the equipment, materials, and process that match the context.")]
    episodic: Annotated[list[MemoryEntry], Field(
        description="Past cases that match the context.")]
    tacit: Annotated[list[TacitItem], Field(
        description="Governed tacit guidance that applies. Empty when none applies.")]
    withheld: _WithheldList
    not_yet_authorised: _NotYetAuthorised
    required_human_actions: Annotated[list[str], Field(
        description="Actions a person must take before you act: escalations, and use "
                    "constraints that call for a person's check. When any is listed, stop and "
                    "hand the decision to a person.")]
    escalation_task_id: _EscalationTask
    governance_notes: Annotated[list[str], Field(
        description="The rules that shaped this context.")]


class MemorySummary(TypedDict):
    """An agent-visible memory object, without its guidance text."""

    memory_id: Annotated[str, Field(description="The memory object's id.")]
    fragment_id: Annotated[str, Field(description="The fragment behind it.")]
    title: Annotated[str, Field(description="A short title.")]
    category: Annotated[str, Field(
        description="Its K1 to K17 category, for example K7_sensory.")]
    authority_layer: Annotated[str, Field(description="advisory or controlled.")]
    conditions: Annotated[dict[str, Any], Field(
        description="The conditions under which it applies: the context fields a retrieval "
                    "must match.")]
    review_due_at: Annotated[str | None, Field(
        description="When reviewers must renew it. After that it drops out until renewed.")]


MemoryListing = Annotated[list[MemorySummary], Field(
    description="Agent-visible memory: promoted, consented, and inside its review date.")]


class ChainStatus(TypedDict):
    """The state of the evidence chain."""

    entries: Annotated[int, Field(description="Entries on the chain.")]
    verified: Annotated[bool, Field(description="True when every hash link verifies.")]


class WorkspaceSummary(TypedDict):
    """The workspace this server serves."""

    workspace: Annotated[str, Field(description="The workspace id.")]
    name: Annotated[str, Field(description="The workspace name.")]
    fragments_by_authority_layer: Annotated[dict[str, int], Field(
        description="Fragment counts per authority layer: evidence (awaiting review), "
                    "advisory, controlled.")]
    agent_visible_memory: Annotated[int, Field(
        description="Memory objects agents may receive now.")]
    pending_whispers: Annotated[int, Field(description="Whispers awaiting a worker's answer.")]
    mission_group_reviewers: Annotated[list[str], Field(
        description="The people who review and promote fragments.")]
    review_rule: Annotated[str, Field(
        description="How many approvals a promotion needs, for example quorum:2.")]
    evidence_chain: Annotated[ChainStatus, Field(description="The evidence chain's state.")]


class Candidate(TypedDict):
    """The candidate account Metis inferred: a hypothesis for the worker to judge."""

    category: Annotated[str, Field(description="Its K1 to K17 category.")]
    hypothesis: Annotated[str, Field(description="The inferred account, in plain words.")]


_Candidate = Annotated[Candidate, Field(
    description="The candidate account Metis inferred, for the worker to confirm or correct.")]
_Deferred = Annotated[bool, Field(
    description="True when the worker had reached the whisper budget and nothing was asked.")]
_Repeated = Annotated[bool, Field(
    description="True when this observation was reported before and its whisper is returned "
                "again.")]
_Question = Annotated[str, Field(description="The question to put to the worker.")]
_Options = Annotated[list[str], Field(description="The answers the worker can give.")]


class ObservationResult(TypedDict, total=False):
    """The whisper Metis raised for an observation, or the reason it asked nothing."""

    deferred: Required[_Deferred]
    note: Required[Annotated[str, Field(description="What to do next.")]]
    reason: Annotated[str | None, Field(description="Why the capture was deferred.")]
    repeated: _Repeated
    whisper_id: Annotated[str, Field(description="The whisper's id, for answer_whisper.")]
    worker: Annotated[str, Field(description="The worker who is asked.")]
    question: _Question
    options: _Options
    candidate: _Candidate


class PendingWhisper(TypedDict):
    """A whisper waiting for a worker's answer."""

    whisper_id: Annotated[str, Field(description="The whisper's id, for answer_whisper.")]
    worker: Annotated[str, Field(description="The worker it is addressed to.")]
    question: _Question
    options: _Options
    observation: Annotated[str, Field(description="The observed practice it asks about.")]
    candidate_category: Annotated[str, Field(description="The inferred K1 to K17 category.")]


PendingWhispers = Annotated[list[PendingWhisper], Field(
    description="Whispers awaiting an answer, oldest first.")]


class AnswerResult(TypedDict, total=False):
    """What the worker's answer stored."""

    stored: Required[Annotated[bool, Field(
        description="True when the answer stored a fragment.")]]
    note: Required[Annotated[str, Field(description="What happens next.")]]
    fragment_id: Annotated[str, Field(description="The stored fragment.")]
    authority_layer: Annotated[str, Field(
        description="evidence: visible to agents only after reviewers promote it.")]
    validation_state: Annotated[str, Field(description="Its validation state.")]
    consent: Annotated[str, Field(description="The worker's recorded consent.")]


class ContestResult(TypedDict, total=False):
    """The recorded contest and what it set in motion."""

    recorded: Required[Annotated[bool, Field(description="True once the contest is recorded.")]]
    action: Required[Annotated[str, Field(description="The contest action recorded.")]]
    contestability_record: Annotated[str, Field(
        description="The evidence-chain artefact recording the contest.")]
    mission_group_task: Annotated[str, Field(
        description="The Mission Group review the contest opened or joined.")]
    revocation: Annotated[str, Field(
        description="The artefact recording the revocation, after withdraw.")]
    re_elicitation_request: Annotated[str, Field(
        description="The artefact asking the worker to give the account again.")]


class ChainCheck(TypedDict):
    """The result of verifying the evidence chain and its ledger."""

    entries: Annotated[int, Field(description="Entries checked on the chain.")]
    verified: Annotated[bool, Field(description="True when every hash link verifies.")]
    errors: Annotated[list[str], Field(description="Each problem found. Empty when verified.")]
    ledger_entries: Annotated[int | None, Field(
        description="Entries in the append-only ledger, when the workspace keeps one.")]
    ledger_agrees: Annotated[bool | None, Field(
        description="True when the ledger matches the chain entry for entry.")]


ChainEntry = TypedDict("ChainEntry", {
    "seq": Annotated[int, Field(description="The entry's sequence number.")],
    "method": Annotated[str, Field(
        description="The CHAP method recorded, for example task.create or whisper.ask.")],
    "from": Annotated[str, Field(description="The participant who sent it.")],
})
ChainEntry.__doc__ = "One entry on the evidence chain."

ChainTail = Annotated[list[ChainEntry], Field(description="The latest entries, newest last.")]


# ---- results of the remote endpoint ------------------------------------------------------

class WorkspaceAccess(TypedDict):
    """A workspace you belong to, with your roles there."""

    id: Annotated[str, Field(description="The workspace id, for the other tools.")]
    name: Annotated[str, Field(description="The workspace name.")]
    site: Annotated[str, Field(description="The site it serves.")]
    created_at: Annotated[str, Field(description="When it was created.")]
    updated_at: Annotated[str, Field(description="When it last changed.")]
    your_roles: Annotated[list[str], Field(
        description="Your roles: agent, capture, worker, reviewer, escalation, auditor, or "
                    "admin.")]


WorkspaceList = Annotated[list[WorkspaceAccess], Field(
    description="The workspaces you belong to; every workspace for an auditor.")]


class Member(TypedDict, total=False):
    """A participant on the workspace's evidence chain."""

    uri: Annotated[str, Field(description="The participant URI.")]
    role: Annotated[str, Field(description="Their role on the chain.")]


class WorkspaceDetails(TypedDict, total=False):
    """One workspace: its governance settings, evidence chain, and your roles."""

    id: Annotated[str, Field(description="The workspace id.")]
    name: Annotated[str, Field(description="The workspace name.")]
    created: Annotated[str, Field(description="When it was created.")]
    state: Annotated[str, Field(description="Its state, for example active.")]
    mode: Annotated[str, Field(description="Its CHAP mode, for example production.")]
    mode_ceiling: Annotated[str, Field(description="The highest mode it may run in.")]
    coordinator: Annotated[str, Field(description="The CHAP coordinator service URI.")]
    members: Annotated[list[Member], Field(description="Participants on the evidence chain.")]
    profiles: Annotated[list[str], Field(description="The CHAP profiles it runs.")]
    evidence_head: Annotated[str, Field(description="The hash at the head of the chain.")]
    evidence_count: Annotated[int, Field(description="Entries on the chain.")]
    review_rule: Annotated[str, Field(
        description="How many approvals a promotion needs, for example quorum:2.")]
    reviewers: Annotated[int, Field(description="Mission Group reviewers.")]
    escalation_assignee: Annotated[str | None, Field(
        description="The person who decides escalated retrievals.")]
    whisper_deadline_ms: Annotated[int | None, Field(
        description="How long a whisper waits for its answer before it lapses.")]
    agent_visible_memory: Annotated[int, Field(
        description="Memory objects agents may receive now.")]
    evidence_verified: Annotated[bool, Field(
        description="True when every hash link verifies.")]
    your_roles: Annotated[list[str], Field(description="Your roles in this workspace.")]


class EscalatedFragment(TypedDict, total=False):
    """A fragment the gate handed to a person."""

    fragment_id: Annotated[str | None, Field(description="The fragment.")]
    reason: Annotated[str, Field(description="Why the gate handed it over.")]
    detail: Annotated[str | None, Field(description="Specifics of the reason.")]


class EscalationDecisionView(TypedDict, total=False):
    """A person's decision on an escalated retrieval."""

    task_id: Annotated[str, Field(description="The escalation.")]
    outcome: Annotated[str, Field(
        description="applies (use the guidance here), does_not_apply (do not), or "
                    "refer_to_review (the Mission Group reviews the fragment).")]
    decided_by: Annotated[str, Field(description="The person who decided.")]
    rationale: Annotated[str, Field(description="Their reason.")]
    fragments: Annotated[list[str], Field(description="The fragments decided.")]
    runtime_context: Annotated[dict[str, Any], Field(description="The situation decided.")]
    requested_by: Annotated[str | None, Field(description="The agent that asked.")]
    review_tasks: Annotated[list[str], Field(
        description="Mission Group reviews opened by refer_to_review.")]


class EscalationStatus(TypedDict, total=False):
    """An escalation and the person's decision on it."""

    task_id: Required[Annotated[str, Field(description="The escalation.")]]
    state: Annotated[str, Field(description="Its state, for example in_progress or completed.")]
    assignee: Annotated[str | None, Field(description="The person asked to decide.")]
    requested_by: Annotated[str | None, Field(description="The agent whose retrieval escalated.")]
    created_at: Annotated[str, Field(description="When it was opened.")]
    runtime_context: Annotated[dict[str, Any] | None, Field(
        description="The situation the retrieval described.")]
    fragments: Annotated[list[EscalatedFragment], Field(description="What the gate handed over.")]
    origin_task: Annotated[str | None, Field(description="The retrieval that escalated.")]
    decision: Annotated[EscalationDecisionView | None, Field(
        description="The decision, or null while the person has not decided.")]
    next_step: Annotated[str, Field(description="What to do now that the decision is made.")]


class ServerObservationResult(TypedDict, total=False):
    """The whisper the observation raised in the worker's inbox, or the reason it asked
    nothing."""

    deferred: Required[_Deferred]
    worker: Annotated[str, Field(description="The worker who is asked.")]
    reason: Annotated[str | None, Field(description="Why the capture was deferred.")]
    note: Annotated[str, Field(description="What happened, when nothing was asked.")]
    repeated: _Repeated
    whisper_id: Annotated[str, Field(description="The whisper's id.")]
    question: _Question
    options: _Options
    observation: Annotated[str, Field(description="The observed practice it asks about.")]
    candidate: _Candidate
    submitted_by: Annotated[str, Field(description="Who reported the observation.")]
    asked_at: Annotated[str | None, Field(description="When the whisper was raised.")]
