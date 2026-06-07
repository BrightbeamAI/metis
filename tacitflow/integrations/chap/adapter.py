"""CHAPAdapter, the single object TacitFlow uses to speak CHAP.

It owns a workspace descriptor, an append-only evidence chain, a keyring, an id factory,
and registries of participants / tasks / artefacts. Every TacitFlow action is emitted as
a signed CHAP envelope (request/notification), recorded in the evidence chain, and, when
it produces a record, carried as a CHAP artefact. TacitFlow defines NO new protocol; it
maps onto CHAP Core plus the whisper, review, routing, control, and handoff profiles.
"""
from __future__ import annotations

import copy
import datetime as _dt
from typing import Any

from .artefacts import build_artefact
from .canonical import ZERO_HASH
from .crypto import Keyring
from .envelope import build_envelope
from .evidence import EvidenceChain, EvidenceEntry
from .ids import IdFactory
from .participants import participant_descriptor, type_of, validate_uri
from .tasks import build_task
from .workspace import workspace_descriptor

DEFAULT_PROFILES = [
    "core/1.0",
    "review/1.0",
    "whisper/1.0",
    "routing/1.0",
    "control/1.0",
    "handoff/1.0",
    "modes/1.0",
    "tacitflow/1.0",
]
_DET_EPOCH = _dt.datetime(2026, 1, 5, 9, 0, 0, tzinfo=_dt.timezone.utc)


class CHAPAdapter:
    def __init__(
        self,
        workspace_id: str,
        name: str,
        *,
        profiles: list[str] | None = None,
        deterministic: bool = True,
        mode: str = "trial",
        mode_ceiling: str = "production",
        coordinator: str = "service:coordinator@tacitflow.local",
    ) -> None:
        if not workspace_id.startswith("wsp_"):
            workspace_id = "wsp_" + workspace_id
        self.workspace_id = workspace_id
        self.name = name
        self.coordinator = coordinator
        self.profiles = profiles or list(DEFAULT_PROFILES)
        self.mode = mode
        self.mode_ceiling = mode_ceiling
        self.deterministic = deterministic

        self.ids = IdFactory(deterministic=deterministic)
        self.keyring = Keyring()
        self.chain = EvidenceChain(workspace_id)
        self.participants: dict[str, dict[str, Any]] = {}
        self.members: list[dict[str, Any]] = []
        self.tasks: dict[str, dict[str, Any]] = {}
        self.artefacts: dict[str, dict[str, Any]] = {}
        self.artefact_evidence: dict[str, int] = {}  # artefact_id -> evidence seq
        self._ts_ms = int(_DET_EPOCH.timestamp() * 1000)

        # The coordinator is a service participant and signs the genesis message.
        self.keyring.key_for(coordinator)
        self._emit(
            "workspace.create",
            sender=coordinator,
            params={
                "workspace": workspace_id,
                "name": name,
                "profiles": self.profiles,
                "mode": mode,
                "mode_ceiling": mode_ceiling,
                "ts": self.now_iso(),
            },
            to=coordinator,
        )

    # ---- time -----------------------------------------------------------------
    def now_iso(self) -> str:
        if self.deterministic:
            self._ts_ms += 1000
            dt = _dt.datetime.fromtimestamp(self._ts_ms / 1000, tz=_dt.timezone.utc)
        else:
            dt = _dt.datetime.now(_dt.timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    # ---- low-level emit --------------------------------------------------------
    def _emit(
        self,
        method: str,
        *,
        sender: str,
        params: dict[str, Any],
        to: str | list[str] | None = None,
        msg_type: str = "request",
    ) -> EvidenceEntry:
        validate_uri(sender)
        key = self.keyring.key_for(sender)
        envelope = build_envelope(
            envelope_id=self.ids.envelope_id(),
            ts=params.get("ts") or self.now_iso(),
            workspace=self.workspace_id,
            sender=sender,
            to=to or self.coordinator,
            method=method,
            params=params,
            prev_hash=ZERO_HASH,  # set correctly by the chain on append
            msg_type=msg_type,
        )
        return self.chain.append(envelope, key)

    # ---- participants ----------------------------------------------------------
    def join(
        self,
        uri: str,
        role: str,
        *,
        display_name: str | None = None,
        capabilities: dict[str, Any] | None = None,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        validate_uri(uri)
        self.keyring.key_for(uri)
        desc = participant_descriptor(
            uri,
            self.keyring.jwk(uri),
            display_name=display_name,
            capabilities=capabilities,
            scopes=scopes,
        )
        self.participants[uri] = desc
        self.members.append({"uri": uri, "role": role, "joined": self.now_iso()})
        self._emit(
            "participant.join",
            sender=uri,
            params={
                "workspace": self.workspace_id,
                "from": uri,
                "type": type_of(uri),
                "role": role,
                "ts": self.now_iso(),
            },
            to=self.coordinator,
        )
        return desc

    # ---- tasks -----------------------------------------------------------------
    def create_task(
        self,
        kind: str,
        *,
        assignee: str,
        delegator: str,
        task_input: Any | None = None,
        routing_hints: dict[str, Any] | None = None,
        review: dict[str, Any] | None = None,
        parent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        task_id = self.ids.task_id()
        task = build_task(
            task_id=task_id,
            workspace=self.workspace_id,
            kind=kind,
            assignee=assignee,
            delegator=delegator,
            created=self.now_iso(),
            mode=self.mode,
            task_input=task_input,
            routing_hints=routing_hints,
            review=review,
            parent=parent,
            metadata=metadata,
        )
        self.tasks[task_id] = task
        self._emit(
            "task.create",
            sender=delegator,
            params={
                "workspace": self.workspace_id,
                "from": delegator,
                "task": copy.deepcopy(task),
                "ts": self.now_iso(),
            },
            to=assignee,
        )
        return task_id

    def update_task(self, task_id: str, state: str, *, sender: str, note: str | None = None) -> None:
        task = self.tasks.get(task_id)
        if task is not None:
            task["state"] = state
            task["updated"] = self.now_iso()
        self._emit(
            "task.update",
            sender=sender,
            params={
                "workspace": self.workspace_id,
                "from": sender,
                "task_id": task_id,
                "state": state,
                "note": note,
                "ts": self.now_iso(),
            },
            to=self.coordinator,
        )

    # ---- artefacts (the workhorse) --------------------------------------------
    def append_artefact(
        self,
        kind: str,
        *,
        produced_by: str,
        content: Any,
        task: str | None = None,
        based_on: str | None = None,
        method: str = "capture.append",
        to: str | list[str] | None = None,
        extra_params: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        logical_id: str | None = None,
        routing_hints: dict[str, Any] | None = None,
        msg_type: str = "request",
    ) -> str:
        artefact_id = self.ids.artefact_id()
        artefact = build_artefact(
            artefact_id=artefact_id,
            kind=kind,
            produced_by=produced_by,
            produced_at=self.now_iso(),
            content=content,
            task=task,
            based_on=based_on,
            tags=tags,
            logical_id=logical_id,
            routing_hints=routing_hints,
        )
        self.artefacts[artefact_id] = artefact
        if task and task in self.tasks:
            self.tasks[task].setdefault("artefacts", []).append(artefact_id)
        params: dict[str, Any] = {
            "workspace": self.workspace_id,
            "from": produced_by,
            "artefact": copy.deepcopy(artefact),
            "ts": self.now_iso(),
        }
        if task:
            params["task_id"] = task
        if extra_params:
            params.update(extra_params)
        entry = self._emit(method, sender=produced_by, params=params, to=to, msg_type=msg_type)
        self.artefact_evidence[artefact_id] = entry.seq
        return artefact_id

    # ---- profile helpers -------------------------------------------------------
    def whisper_ask(
        self,
        *,
        sender: str,
        to: str,
        task_id: str,
        question: str,
        options: list[dict[str, str]],
        deadline_ms: int,
        default_if_lapsed: str,
        urgency: str = "low",
        category: str | None = None,
    ) -> str:
        content = {
            "question": question,
            "options": options,
            "deadline_ms": deadline_ms,
            "default_if_lapsed": default_if_lapsed,
            "urgency": urgency,
            "category": category,
        }
        return self.append_artefact(
            "tacit.whisper_prompt",
            produced_by=sender,
            content=content,
            task=task_id,
            method="whisper.ask",
            to=to,
            extra_params={k: content[k] for k in ("question", "options", "deadline_ms", "default_if_lapsed", "urgency")},
        )

    def whisper_answer(
        self,
        *,
        sender: str,
        to: str,
        task_id: str,
        prompt_artefact: str,
        response_type: str,
        text: str | None = None,
        option_id: str | None = None,
    ) -> str:
        content = {"response_type": response_type, "text": text, "option_id": option_id}
        return self.append_artefact(
            "tacit.whisper_response",
            produced_by=sender,
            content=content,
            task=task_id,
            based_on=prompt_artefact,
            method="whisper.answer",
            to=to,
            extra_params={"response_type": response_type, "answers": option_id or text},
        )

    def review_request(self, *, sender: str, reviewers: list[str], artefact_id: str, task_id: str, rule: str = "any_one_approves") -> EvidenceEntry:
        return self._emit(
            "review.request",
            sender=sender,
            params={
                "workspace": self.workspace_id,
                "from": sender,
                "to": reviewers,
                "artefact_id": artefact_id,
                "task_id": task_id,
                "rule": rule,
                "ts": self.now_iso(),
            },
            to=reviewers,
        )

    def decide(self, method: str, *, sender: str, based_on: str, task_id: str, content: dict[str, Any], to: str | None = None) -> str:
        """Emit a review/decide.* decision and carry its decision artefact."""
        return self.append_artefact(
            "decision",
            produced_by=sender,
            content={"method": method, **content},
            task=task_id,
            based_on=based_on,
            method=method,
            to=to,
        )

    def control_event(self, method: str, *, sender: str, params: dict[str, Any], to: str | None = None) -> EvidenceEntry:
        base = {"workspace": self.workspace_id, "from": sender, "ts": self.now_iso()}
        base.update(params)
        return self._emit(method, sender=sender, params=base, to=to or self.coordinator)

    # ---- queries ---------------------------------------------------------------
    def artefacts_of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [a for a in self.artefacts.values() if a["kind"] == kind]

    def evidence_records(self) -> list[dict[str, Any]]:
        return [e.to_record() for e in self.chain.entries]

    def descriptor(self) -> dict[str, Any]:
        return workspace_descriptor(
            workspace_id=self.workspace_id,
            name=self.name,
            created=self.now_iso(),
            coordinator=self.coordinator,
            profiles=self.profiles,
            mode=self.mode,
            mode_ceiling=self.mode_ceiling,
            members=self.members,
            evidence_head=self.chain.head,
            evidence_count=self.chain.count,
        )

    def verify(self):
        return self.chain.verify()
