"""Deriving notifications from what a write recorded.

The planner compares a workspace before and after a write: new whispers, escalations, and
review activity show up as changes in state, and new decisions show up as artefacts on the
chain. It runs inside the write's transaction, so a notification exists only for what was
committed.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from ..governance.membership import Role
from ..guidance import overdue
from ..integrations.chap.participants import type_of
from ..taxonomy.categories import RevocationStatus, ValidationState
from .events import Notification

_IN_USE = (ValidationState.promoted_to_advisory, ValidationState.promoted_to_controlled)


@dataclass
class WorkspaceView:
    """The parts of a workspace whose changes people hear about."""

    chain: int
    pending: dict[str, str] = field(default_factory=dict)        # whisper id -> worker
    escalations: set[str] = field(default_factory=set)           # open escalation task ids
    reviews: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = field(default_factory=dict)
    # fragment id -> (review task, addressed reviewers, approving reviewers)


def _review_state(engine: Any, fragment_id: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    task_id = engine.governance.refs[fragment_id]["task"]
    ws = engine.adapter.coord.get_workspace(engine.adapter.workspace_id)
    review = getattr(ws.tasks.get(task_id), "review", None) if ws else None
    addressed = tuple(getattr(review, "requested_to", None) or ())
    approvers = tuple(dict.fromkeys(d["reviewer"] for d in getattr(review, "decisions", None) or []
                                    if d.get("kind") == "approve"))
    return task_id, addressed, approvers


def observe(engine: Any) -> WorkspaceView:
    view = WorkspaceView(chain=engine.adapter.chain.count)
    view.pending = {wid: p.worker for wid, p in engine.pending_captures.items() if not p.deferred}
    view.escalations = {t["task_id"] for t in engine.escalation_tasks()}
    for fragment in engine.fragments.all():
        if engine.governance.review_open(fragment.fragment_id):
            view.reviews[fragment.fragment_id] = _review_state(engine, fragment.fragment_id)
    return view


class Planner:
    """Turns the difference between two views, and the chain entries in between, into
    notifications."""

    def _note(self, engine: Any, event: str, recipients: list[str], **subject: Any) -> Notification:
        return Notification(event=event, workspace_id=engine.adapter.workspace_id,
                            workspace_name=engine.adapter.name, recipients=recipients,
                            subject={k: v for k, v in subject.items() if v is not None})

    @staticmethod
    def _people(engine: Any, uris: Any) -> list[str]:
        """The reviewers among ``uris``: named human members with the reviewer role."""
        reviewers = set(engine.mission_group_members)
        return [u for u in uris if u in reviewers]

    @staticmethod
    def _contributor(engine: Any, fragment_id: str | None) -> list[str]:
        frag = engine.fragments.get(fragment_id) if fragment_id else None
        who = frag.provenance.originating_participant if frag else None
        return [who] if who and type_of(who) == "human" else []

    @staticmethod
    def _title(engine: Any, fragment_id: str | None) -> str | None:
        frag = engine.fragments.get(fragment_id) if fragment_id else None
        return frag.title if frag else None

    def plan(self, engine: Any, before: WorkspaceView, after: WorkspaceView) -> list[Notification]:
        notes: list[Notification] = []
        need = engine.governance.policy.approvals_required(len(engine.mission_group_members))

        for wid, worker in after.pending.items():
            if wid not in before.pending:
                pending = engine.pending_captures[wid]
                notes.append(self._note(
                    engine, "whisper.asked", [worker], whisper_id=wid,
                    question=pending.whisper.question if pending.whisper else None,
                    observation=pending.observation.work_as_done or pending.observation.text,
                    options=[o["id"] for o in pending.whisper.options] if pending.whisper else None))

        for task_id in sorted(after.escalations - before.escalations):
            task = next(t for t in engine.escalation_tasks() if t["task_id"] == task_id)
            notes.append(self._note(
                engine, "escalation.opened", [m.uri for m in engine.members_with(Role.escalation)],
                task_id=task_id, requested_by=task["requested_by"],
                fragments=[f.get("fragment_id") for f in task["fragments"]],
                reasons=[f.get("reason") for f in task["fragments"]]))

        for fid, (task, addressed, approvers) in after.reviews.items():
            old = before.reviews.get(fid)
            title = self._title(engine, fid)
            if old is None or old[0] != task:
                notes.append(self._note(engine, "review.requested",
                                        [u for u in self._people(engine, addressed) if u not in approvers],
                                        fragment_id=fid, title=title, review_task=task))
                continue
            added = [u for u in addressed if u not in old[1]]
            if added:
                notes.append(self._note(engine, "review.requested", self._people(engine, added),
                                        fragment_id=fid, title=title, review_task=task))
            if len(approvers) > len(old[2]):
                proposal = engine.governance.proposals.get(fid) or {}
                notes.append(self._note(
                    engine, "review.approval",
                    [u for u in self._people(engine, addressed) if u not in approvers],
                    fragment_id=fid, title=title, review_task=task, approvals=len(approvers),
                    required=need, outcome=proposal.get("outcome")))

        for entry in engine.adapter.chain.entries[before.chain:]:
            notes.extend(self._from_entry(engine, entry))
        return [n for n in notes if n.recipients]

    def _from_entry(self, engine: Any, entry: Any) -> list[Notification]:
        params = entry.envelope.get("params") or {}
        output = params.get("output")
        if entry.envelope.get("method") != "task.complete" or not isinstance(output, dict):
            return []
        kind, content = output.get("kind"), output.get("content") or {}
        if not isinstance(content, dict):
            return []
        fid = content.get("fragment_id")
        reviewers = list(engine.mission_group_members)
        if kind == "tacit.review_decision":
            return [self._note(engine, "review.decided",
                               self._contributor(engine, fid) + reviewers, fragment_id=fid,
                               title=self._title(engine, fid), outcome=content.get("outcome"))]
        if kind == "tacit.validation_event" and content.get("event") == "contestability":
            raiser = content.get("raised_by")
            return [self._note(engine, "fragment.contested",
                               [u for u in reviewers + self._contributor(engine, fid) if u != raiser],
                               fragment_id=fid, title=self._title(engine, fid),
                               action=content.get("action"))]
        if kind == "tacit.validation_event" and content.get("event") == "whisper_lapsed":
            ws = engine.adapter.coord.get_workspace(engine.adapter.workspace_id)
            task = ws.tasks.get(output.get("task")) if ws and output.get("task") else None
            reporter = task.delegator if task else None
            worker = content.get("worker")
            return [self._note(engine, "whisper.lapsed",
                               [reporter] if reporter and reporter != worker else [],
                               worker=worker, whisper_id=output.get("based_on"))]
        if kind == "tacit.revocation_record":
            actor = content.get("actioned_by")
            return [self._note(engine, "fragment.revoked",
                               [u for u in reviewers + self._contributor(engine, fid) if u != actor],
                               fragment_id=fid, title=self._title(engine, fid),
                               status=content.get("new_status"), reason=content.get("reason"))]
        if kind == "tacit.escalation_decision":
            decider = content.get("decided_by")
            audience = [content.get("requested_by")] + [m.uri for m in engine.members_with(Role.escalation)]
            return [self._note(engine, "escalation.decided",
                               [u for u in audience if u and u != decider],
                               task_id=content.get("task_id"), outcome=content.get("outcome"),
                               fragments=content.get("fragments"))]
        if kind == "tacit.membership_record":
            who = content.get("participant")
            return [self._note(engine, "member.changed",
                               [who] if who and who != content.get("actioned_by") else [],
                               roles=content.get("roles"), granted=content.get("granted"),
                               revoked=content.get("revoked"))]
        return []

    def review_due(self, engine: Any, now: _dt.datetime) -> list[Notification]:
        """Notices for fragments in use past their review date, once per review date."""
        notes = []
        for frag in engine.fragments.all():
            if (frag.validation_state in _IN_USE and frag.revocation_status == RevocationStatus.active
                    and overdue(frag, now) and not engine.governance.review_open(frag.fragment_id)):
                note = self._note(engine, "fragment.review_due", list(engine.mission_group_members),
                                  fragment_id=frag.fragment_id, title=frag.title,
                                  review_due_at=frag.review_due_at)
                note.dedupe_key = (f"review_due:{engine.adapter.workspace_id}:"
                                   f"{frag.fragment_id}:{frag.review_due_at}")
                if note.recipients:
                    notes.append(note)
        return notes
