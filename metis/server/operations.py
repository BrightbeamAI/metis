"""What agents and capture sources do, shared by the HTTP API and the remote MCP endpoint.

Each operation takes the repository, the signed-in principal, and its arguments, checks the
principal's roles in the workspace, and runs as a read or as the workspace's one writer. Both
surfaces call these, so they apply the same rules.
"""
from __future__ import annotations

from typing import Any

from .. import guidance as views
from ..consent.model import ConsentRecord, ConsentStatus
from ..governance.lifecycle import contributed
from ..governance.membership import Role
from ..identity import Principal
from ..limits import MAX_ID, MAX_NAME, MAX_TEXT, MAX_URI, check_text
from ..validation.states import InvalidTransition
from .access import Forbidden, require, require_member, roles_in
from .deps import NotFound

RISK_CLASSES = ("low", "moderate", "high", "critical")


def _model(repo: Any) -> Any:
    """The live local model, when one is configured; drafting then happens before the write."""
    return getattr(repo, "model_client", lambda: None)()


def capture_drafts(repo: Any, observation_input: dict[str, Any], category: str | None) -> Any:
    """The model's drafts for a capture, made before the workspace is locked (``None`` with
    deterministic drafting, which the engine does in place)."""
    client = _model(repo)
    if client is None:
        return None
    from ..capture.loop import draft_capture

    return draft_capture(observation_input, model_client=client, category=category)


def answer_draft(repo: Any, workspace_id: str, whisper_id: str, worker: str, response: str,
                 corrected_text: str | None = None, free_text: str | None = None) -> Any:
    """The model's summary of a worker's answer, drafted before the workspace is locked."""
    client = _model(repo)
    if client is None or response not in ("confirm", "correct"):
        return None

    def asked(engine: Any) -> Any:
        pending = engine.pending_captures.get(whisper_id)
        if pending is None or pending.worker != worker or pending.whisper is None:
            return None
        return pending.whisper, pending.candidate.hypothesis
    seen = repo.read(workspace_id, asked)
    if seen is None:
        return None
    from ..capture.loop import draft_confirmation

    return draft_confirmation(seen[0], response, model_client=client,
                              corrected_content=corrected_text, free_text=free_text,
                              confirmed_text=seen[1])


def agent_context_of(context: dict[str, Any]) -> Any:
    """An agent's work situation. It must name its risk class: Metis hands high-risk
    situations to a person, so a missing risk class is refused, never assumed low."""
    risk = context.get("risk_class")
    if risk not in RISK_CLASSES:
        raise ValueError(f"Give the situation's risk_class in the context: one of "
                         f"{', '.join(RISK_CLASSES)}.")
    return views.context_from(context)


def workspaces(repo: Any, p: Principal) -> list[dict[str, Any]]:
    """The workspaces the caller can see, with the caller's roles in each."""
    mine = repo.memberships(p.uri)
    return [{"id": w.id, "name": w.name, "site": w.site, "created_at": w.created_at,
             "updated_at": w.updated_at, "your_roles": mine.get(w.id, [])}
            for w in repo.list() if p.is_auditor or w.id in mine]


def describe(repo: Any, p: Principal, workspace_id: str) -> dict[str, Any]:
    def view(engine: Any) -> dict[str, Any]:
        roles = require_member(engine, p)
        chain = engine.verify()
        return {**engine.adapter.descriptor(),
                "review_rule": engine.governance.policy.review_rule,
                "reviewers": len(engine.mission_group_members),
                "escalation_assignee": engine.escalation_assignee,
                "whisper_deadline_ms": engine.capture.whisper_deadline_ms,
                "agent_visible_memory": len(views.visible_memory(engine)),
                "evidence_verified": chain.ok,
                "your_roles": sorted(r.value for r in roles)}
    return repo.read(workspace_id, view)


def retrieve(repo: Any, p: Principal, workspace_id: str, context: dict[str, Any],
             role: str | None = None) -> dict[str, Any]:
    """Governed guidance for a work situation, recorded under the agent's identity."""
    ctx = agent_context_of(context)

    def ask(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.agent)
        decision = engine.retrieve(ctx, role=role, requester=p.uri)
        return views.guidance_view(engine, decision)
    return repo.write(workspace_id, ask)


def agent_context(repo: Any, p: Principal, workspace_id: str, task: str, context: dict[str, Any],
                  role: str | None = None) -> dict[str, Any]:
    ctx = agent_context_of(context)

    def ask(engine: Any) -> dict[str, Any]:
        require(engine, p, Role.agent)
        amc = engine.agent_context(task, ctx, role=role, requester=p.uri)
        return views.agent_context_view(engine, amc)
    return repo.write(workspace_id, ask)


def memory(repo: Any, p: Principal, workspace_id: str) -> list[dict[str, Any]]:
    def view(engine: Any) -> list[dict[str, Any]]:
        require(engine, p, Role.agent, Role.reviewer, Role.auditor, Role.admin,
                global_auditor=True)
        return views.memory_listing(engine)
    return repo.read(workspace_id, view)


def escalation(repo: Any, p: Principal, workspace_id: str, task_id: str) -> dict[str, Any]:
    """One escalation and any decision on it, for people and for the agent that asked."""
    def view(engine: Any) -> dict[str, Any]:
        item = next((t for t in engine.escalation_tasks(open_only=False)
                     if t["task_id"] == task_id), None)
        readers = {Role.escalation, Role.reviewer, Role.auditor, Role.admin}
        if item is None or not (roles_in(engine, p) & readers or p.is_auditor
                                or item["requested_by"] == p.uri):
            raise NotFound(f"No escalation {task_id}.")
        outcome = (item.get("decision") or {}).get("outcome")
        if outcome == "applies":
            hours = engine.escalations.grant_hours
            item = {**item, "next_step": (
                f"Ask again with the same context within {hours:g} hours: the guidance a person "
                "said applies is given then, and the retrieval is recorded.")}
        elif outcome:
            item = {**item, "next_step": "Do not use the withheld guidance in this situation."}
        return item
    return repo.read(workspace_id, view)


def whisper_view(engine: Any, pending: Any) -> dict[str, Any]:
    prompt = engine.adapter.artefacts.get(pending.whisper_id) or {}
    return {"whisper_id": pending.whisper_id, "worker": pending.worker,
            "question": pending.whisper.question,
            "options": [o["id"] for o in pending.whisper.options],
            "observation": pending.observation.work_as_done or pending.observation.text,
            "candidate": {"category": pending.candidate.category,
                          "hypothesis": pending.candidate.hypothesis},
            "submitted_by": pending.submitted_by or pending.worker,
            "asked_at": prompt.get("produced_at")}


def submit_observation(repo: Any, p: Principal, workspace_id: str, *, observation_id: str,
                       work_as_done: str, context: dict[str, Any], worker: str | None = None,
                       work_as_imagined: str | None = None, category: str | None = None,
                       title: str | None = None, supersedes: str | None = None) -> dict[str, Any]:
    """Report where a worker's action differed from the procedure. A capture source may report
    for any worker member; a worker may report their own work. Nothing is stored until the
    worker answers the whisper.

    Reporting the same observation again (a retry) returns the whisper it raised; another
    observation under a recorded id is refused. A fragment awaiting re-elicitation is replaced
    only by a capture from the worker who contributed it."""
    for name, value, limit in (("observation_id", observation_id, MAX_ID),
                               ("work_as_done", work_as_done, MAX_TEXT),
                               ("work_as_imagined", work_as_imagined, MAX_TEXT),
                               ("worker", worker, MAX_URI), ("category", category, MAX_NAME),
                               ("title", title, MAX_NAME), ("supersedes", supersedes, MAX_ID)):
        check_text(name, value, limit)
    ctx = views.context_from(context)
    observation_input = {"observation_id": observation_id, "work_as_imagined": work_as_imagined,
                         "work_as_done": work_as_done, "context": ctx, "source": "api"}
    asked = worker or p.uri

    def may_report(engine: Any) -> None:
        roles = roles_in(engine, p)
        if Role.capture not in roles and not (Role.worker in roles and asked == p.uri):
            raise Forbidden("Reporting an observation needs the capture role, or the worker role "
                            "for your own work.")
        if Role.worker not in engine.roles_of(asked):
            raise Forbidden(f"{asked} is not a worker in {workspace_id}.")

    drafts = None
    if _model(repo) is not None:  # ask the model only for a new observation the caller may report
        def new_and_allowed(engine: Any) -> bool:
            may_report(engine)
            return not engine.observation_seen(observation_id)
        if repo.read(workspace_id, new_and_allowed):
            drafts = capture_drafts(repo, observation_input, category)

    def capture(engine: Any) -> dict[str, Any]:
        may_report(engine)
        if engine.observation_seen(observation_id):
            same = next((c for c in engine.pending_captures.values()
                         if c.observation.observation_id == observation_id), None)
            if (same is not None and same.worker == asked
                    and same.observation.work_as_done == work_as_done):
                return {"deferred": False, "repeated": True, **whisper_view(engine, same)}
            raise InvalidTransition(f"Observation {observation_id} was reported already; give a "
                                    "new observation a new id.")
        if supersedes is not None:
            old = engine.fragments.get(supersedes)
            if old is not None and not contributed(old, asked):
                raise Forbidden(f"Only the worker who contributed {supersedes} gives the account "
                                "that replaces it.")
        pending = engine.begin_capture(
            observation_input, consent=ConsentRecord(consent_status=ConsentStatus.pending),
            worker=asked, submitted_by=None if asked == p.uri else p.uri, category=category,
            title=title, conditions=ctx, supersedes=supersedes, drafts=drafts)
        if pending.deferred:
            return {"deferred": True, "reason": pending.deferred_reason, "worker": asked,
                    "note": "The worker has reached the whisper budget; nothing was asked."}
        return {"deferred": False, **whisper_view(engine, pending)}
    return repo.write(workspace_id, capture)


MAX_INGEST_BATCH = 1000
INGEST_CHUNK = 50  # records committed per transaction, so no write holds a workspace for long


def ingest(repo: Any, p: Principal, workspace_id: str, mapping: Any,
           records: list[Any]) -> dict[str, Any]:
    """Map records from a source and capture each new one for its worker.

    Records are committed in transactions of ``INGEST_CHUNK``. A record whose observation id is
    already recorded is a duplicate and is skipped, so a source may send the same records again
    (after a failure part-way, the records committed before it are reported as duplicates). A
    record that fails its mapping or the size limits, names someone who is not a worker, or
    carries an invalid category or context is reported and skipped before anything is recorded
    for it.
    """
    from ..connectors.mapping import map_records
    from ..taxonomy.categories import Category

    if len(records) > MAX_INGEST_BATCH:
        raise ValueError(f"Send at most {MAX_INGEST_BATCH} records at a time; got {len(records)}.")
    mapped, failed = map_records(mapping, records)
    totals: dict[str, Any] = {"source": mapping.name, "records": len(records), "accepted": [],
                              "duplicates": [], "failed": list(failed),
                              "filtered": len(records) - len(mapped) - len(failed)}

    def inputs(obs: Any) -> dict[str, Any]:
        return {"observation_id": obs.observation_id, "work_as_imagined": obs.work_as_imagined,
                "work_as_done": obs.work_as_done, "context": views.context_from(obs.context),
                "source": mapping.name}

    draftable: set[str] = set()
    if _model(repo) is not None and mapped:
        def new_records(engine: Any) -> set[str]:
            require(engine, p, Role.capture)
            return {o.observation_id for o in mapped if not engine.observation_seen(o.observation_id)
                    and Role.worker in engine.roles_of(o.worker)}
        draftable = repo.read(workspace_id, new_records)

    def drafted(chunk: list[Any]) -> dict[str, Any]:
        """Model drafts for a chunk's new records, made before its write (none with deterministic
        drafting, which the engine does in place)."""
        out = {}
        for obs in chunk:
            if obs.observation_id not in draftable:
                continue
            try:
                out[obs.observation_id] = capture_drafts(repo, inputs(obs), obs.category)
            except ValueError:  # reported when the chunk is written
                continue
        return out

    def capture(engine: Any, chunk: list[Any], drafts: dict[str, Any]) -> dict[str, Any]:
        require(engine, p, Role.capture)
        accepted: list[dict[str, Any]] = []
        duplicates: list[str] = []
        problems: list[dict[str, Any]] = []
        for obs in chunk:
            if engine.observation_seen(obs.observation_id):
                duplicates.append(obs.observation_id)
                continue
            try:
                for name, value, limit in (("id", obs.observation_id, MAX_ID),
                                           ("work_as_done", obs.work_as_done, MAX_TEXT),
                                           ("work_as_imagined", obs.work_as_imagined, MAX_TEXT),
                                           ("title", obs.title, MAX_NAME)):
                    check_text(name, value, limit)
                if Role.worker not in engine.roles_of(obs.worker):
                    raise ValueError(f"{obs.worker} is not a worker in {workspace_id}.")
                if obs.category:
                    Category(obs.category)
                ctx = views.context_from(obs.context)
            except ValueError as exc:  # checked before anything is recorded for this record
                problems.append({"observation_id": obs.observation_id, "error": str(exc)})
                continue
            pending = engine.begin_capture(
                {**inputs(obs), "context": ctx},
                consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=obs.worker,
                submitted_by=None if obs.worker == p.uri else p.uri, category=obs.category,
                title=obs.title, conditions=ctx, drafts=drafts.get(obs.observation_id))
            accepted.append({"observation_id": obs.observation_id, "worker": obs.worker,
                             "whisper_id": pending.whisper_id, "deferred": pending.deferred})
        return {"accepted": accepted, "duplicates": duplicates, "failed": problems}

    if not mapped:  # still check the caller may send to this workspace
        repo.read(workspace_id, lambda e: require(e, p, Role.capture))
    for start in range(0, len(mapped), INGEST_CHUNK):
        chunk = mapped[start:start + INGEST_CHUNK]
        drafts = drafted(chunk)
        part = repo.write(workspace_id, lambda e, c=chunk, d=drafts: capture(e, c, d))
        for key in ("accepted", "duplicates", "failed"):
            totals[key].extend(part[key])
    return totals
