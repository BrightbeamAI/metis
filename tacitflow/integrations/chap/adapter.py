"""CHAPAdapter — the single object TacitFlow uses to speak CHAP.

This adapter drives the official ``chap-coordinator`` reference implementation. It does not
reimplement the protocol: it dispatches JSON-RPC envelopes to a real Coordinator, which owns
the workspace, participants, tasks, and the append-only, hash-linked evidence chain. TacitFlow
maps its domain onto CHAP Core plus the whisper, review, control, and routing profiles, and
keeps a small registry of the artefacts it produces for convenient querying.

The public surface (now_iso, join, create_task, append_artefact, whisper_ask/answer,
review_request, decide, control_event, evidence_records, descriptor, verify, and the
``chain`` / ``artefacts`` / ``artefact_evidence`` attributes) is unchanged, so the rest of
TacitFlow is untouched by the migration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chap_coordinator import ZERO_HASH, Coordinator, CoordinatorOptions, canonicalize, sha256_hex

from .artefacts import build_artefact
from .participants import type_of, validate_uri

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


@dataclass
class VerificationResult:
    ok: bool
    checked: int
    errors: list[str] = field(default_factory=list)


@dataclass
class _Entry:
    """Lightweight handle returned by emit helpers; carries the audit sequence number."""

    seq: int


class ChainView:
    """A read-only view over the Coordinator's per-workspace audit chain."""

    def __init__(self, coord: Coordinator, workspace_id: str) -> None:
        self._coord = coord
        self._ws = workspace_id

    @property
    def _audit(self) -> list:
        ws = self._coord.workspaces.get(self._ws)
        return ws.audit if ws else []

    @property
    def entries(self) -> list:
        return self._audit

    @property
    def count(self) -> int:
        return len(self._audit)

    @property
    def head(self) -> str:
        ws = self._coord.workspaces.get(self._ws)
        return (ws.chain_head if ws and ws.chain_head else ZERO_HASH)

    def verify(self) -> VerificationResult:
        """Recompute the hash-linked chain and confirm prev_hash continuity.

        Mirrors the Coordinator's linkage: ``prev = sha256( JCS(envelope) || prev )``.
        """
        errors: list[str] = []
        prev = ZERO_HASH
        for entry in self._audit:
            ph = getattr(entry, "prev_hash", None)
            if ph is not None and ph != prev:
                errors.append(f"seq {entry.seq}: prev_hash break")
            prev = sha256_hex(canonicalize(entry.envelope) + prev.encode("utf-8"))
        if self._audit and self.head != prev:
            errors.append("chain head mismatch (tamper detected)")
        return VerificationResult(ok=not errors, checked=len(self._audit), errors=errors)


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
        self.coordinator = coordinator  # the Coordinator service URI (string)
        self.profiles = profiles or list(DEFAULT_PROFILES)
        self.mode = mode
        self.mode_ceiling = mode_ceiling
        self.deterministic = deterministic

        # The official CHAP reference implementation owns protocol + evidence.
        self.coord = Coordinator(CoordinatorOptions(
            deterministic_ids=deterministic,
            deterministic_clock=deterministic,
            enable_chain=True,
            default_profiles=list(self.profiles),
        ))
        self._req = 0
        self.participants: dict[str, dict[str, Any]] = {}
        self.members: list[dict[str, Any]] = []
        self.tasks: dict[str, dict[str, Any]] = {}
        self.artefacts: dict[str, dict[str, Any]] = {}
        self.artefact_evidence: dict[str, int] = {}
        self.chain = ChainView(self.coord, self.workspace_id)

        self._dispatch("workspace.create", profiles=list(self.profiles),
                       mode=mode, mode_ceiling=mode_ceiling, **{"from": coordinator})

    # ---- time ------------------------------------------------------------------
    def now_iso(self) -> str:
        return self.coord.now_iso()

    # ---- low-level dispatch ----------------------------------------------------
    def _dispatch(self, method: str, **params: Any) -> dict[str, Any] | None:
        params.setdefault("workspace", self.workspace_id)
        self._req += 1
        envelope = {"jsonrpc": "2.0", "id": str(self._req), "method": method, "params": params}
        resp = self.coord.dispatch(envelope)
        if isinstance(resp, dict) and resp.get("error"):
            raise RuntimeError(f"CHAP {method} failed: {resp['error']}")
        return resp.get("result") if isinstance(resp, dict) else None

    def _last_seq(self) -> int:
        ws = self.coord.workspaces.get(self.workspace_id)
        return (len(ws.audit) - 1) if ws and ws.audit else -1

    def _ensure_member(self, uri: str) -> None:
        validate_uri(uri)
        ws = self.coord.workspaces.get(self.workspace_id)
        if ws is not None and uri in ws.members:
            return
        self._dispatch("participant.join", **{"from": uri}, type=type_of(uri), role="auto")

    # ---- participants ----------------------------------------------------------
    def join(self, uri: str, role: str, *, display_name: str | None = None,
             capabilities: dict[str, Any] | None = None, scopes: list[str] | None = None) -> dict[str, Any]:
        validate_uri(uri)
        params: dict[str, Any] = {"from": uri, "type": type_of(uri), "role": role}
        if display_name:
            params["display_name"] = display_name
        if capabilities:
            params["capabilities"] = capabilities
        if scopes:
            params["scopes"] = scopes
        self._dispatch("participant.join", **params)
        desc = {"uri": uri, "type": type_of(uri), "role": role,
                "display_name": display_name, "capabilities": capabilities}
        self.participants[uri] = desc
        self.members.append({"uri": uri, "role": role})
        return desc

    # ---- tasks -----------------------------------------------------------------
    def create_task(self, kind: str, *, assignee: str, delegator: str,
                    task_input: Any | None = None, routing_hints: dict[str, Any] | None = None,
                    review: dict[str, Any] | None = None, parent: str | None = None,
                    metadata: dict[str, Any] | None = None) -> str:
        self._ensure_member(assignee)
        self._ensure_member(delegator)
        params: dict[str, Any] = {"from": delegator, "kind": kind,
                                  "input": task_input or {}, "assignee": assignee, "mode": "production"}
        if routing_hints:
            params["routing_hints"] = routing_hints
        res = self._dispatch("task.create", **params)
        tid = res["task_id"]
        self.tasks[tid] = {"id": tid, "kind": kind, "assignee": assignee,
                           "delegator": delegator, "artefacts": []}
        return tid

    def update_task(self, task_id: str, state: str, *, sender: str, note: str | None = None) -> None:
        try:
            self._dispatch("task.update", **{"from": sender}, task_id=task_id, state=state, progress_note=note)
        except RuntimeError:
            pass
        if task_id in self.tasks:
            self.tasks[task_id]["state"] = state

    def _record_task(self, kind: str, *, sender: str, task_input: dict[str, Any]) -> str:
        self._ensure_member(sender)
        res = self._dispatch("task.create", **{"from": sender}, kind=kind,
                             input=task_input, assignee=sender, mode="production")
        return res["task_id"]

    # ---- artefacts (recorded as completed CHAP tasks) --------------------------
    def append_artefact(self, kind: str, *, produced_by: str, content: Any, task: str | None = None,
                        based_on: str | None = None, method: str = "capture.append",
                        to: str | list[str] | None = None, extra_params: dict[str, Any] | None = None,
                        tags: list[str] | None = None, logical_id: str | None = None,
                        routing_hints: dict[str, Any] | None = None, msg_type: str = "request") -> str:
        self._ensure_member(produced_by)
        artefact_id = self.coord.ids.artefact_id()
        artefact = build_artefact(
            artefact_id=artefact_id, kind=kind, produced_by=produced_by,
            produced_at=self.now_iso(), content=content, task=task, based_on=based_on,
            tags=tags, logical_id=logical_id, routing_hints=routing_hints)
        self.artefacts[artefact_id] = artefact
        if task and task in self.tasks:
            self.tasks[task].setdefault("artefacts", []).append(artefact_id)
        rec = self._record_task(kind, sender=produced_by,
                                task_input={"records": kind, "about": based_on, "parent_task": task})
        self._dispatch("task.complete", **{"from": produced_by}, task_id=rec, output=artefact)
        self.artefact_evidence[artefact_id] = self._last_seq()
        return artefact_id

    # ---- whisper/1.0 -----------------------------------------------------------
    def whisper_ask(self, *, sender: str, to: str, task_id: str, question: str,
                    options: list[dict[str, str]], deadline_ms: int, default_if_lapsed: str,
                    urgency: str = "low", category: str | None = None) -> str:
        self._ensure_member(sender)
        self._ensure_member(to)
        res = self._dispatch("whisper.ask", **{"from": sender}, to=to, task_id=task_id,
                             question=question, options=options, deadline_ms=deadline_ms,
                             default_if_lapsed=default_if_lapsed, urgency=urgency)
        wid = res["whisper_id"]
        artefact = build_artefact(
            artefact_id=wid, kind="tacit.whisper_prompt", produced_by=sender,
            produced_at=self.now_iso(),
            content={"question": question, "options": options, "deadline_ms": deadline_ms,
                     "default_if_lapsed": default_if_lapsed, "urgency": urgency, "category": category},
            task=task_id)
        self.artefacts[wid] = artefact
        self.artefact_evidence[wid] = self._last_seq()
        return wid

    def whisper_answer(self, *, sender: str, to: str, task_id: str, prompt_artefact: str,
                       response_type: str, text: str | None = None, option_id: str | None = None) -> str:
        self._ensure_member(sender)
        self._dispatch("whisper.answer", **{"from": sender}, whisper_id=prompt_artefact,
                       answer_option=option_id or response_type, answer=text, comment=text)
        return self.append_artefact(
            "tacit.whisper_response", produced_by=sender,
            content={"response_type": response_type, "text": text, "option_id": option_id},
            task=task_id, based_on=prompt_artefact)

    # ---- review/1.0 ------------------------------------------------------------
    def review_request(self, *, sender: str, reviewers: list[str], artefact_id: str,
                       task_id: str, rule: str = "any_one_approves") -> _Entry:
        self._ensure_member(sender)
        revs = reviewers if isinstance(reviewers, list) else [reviewers]
        for r in revs:
            self._ensure_member(r)
        art = self.artefacts.get(artefact_id) or {"id": artefact_id}
        self._dispatch("review.request", **{"from": sender}, task_id=task_id, to=revs, artefact=art, rule=rule)
        return _Entry(seq=self._last_seq())

    def decide(self, method: str, *, sender: str, based_on: str | None, task_id: str,
               content: dict[str, Any], to: str | None = None) -> None:
        self._ensure_member(sender)
        comment = content.get("summary") or content.get("outcome") or ""
        if method == "abstain.declare":
            self._dispatch("abstain.declare", **{"from": sender}, task_id=task_id, reason=comment or "held")
        elif method == "escalate.raise":
            self._dispatch("escalate.raise", **{"from": sender}, original_task_id=task_id,
                           new_task={"kind": "tacit.re_elicit",
                                     "input": {"about": based_on, "reason": comment},
                                     "assignee": sender})
        else:
            tags = [content["outcome"]] if content.get("outcome") else []
            self._dispatch(method, **{"from": sender}, task_id=task_id, comment=comment, tags=tags)
        return None

    # ---- control/1.0 -----------------------------------------------------------
    def control_event(self, method: str, *, sender: str, params: dict[str, Any], to: str | None = None) -> _Entry:
        self._ensure_member(sender)
        clean = {k: v for k, v in params.items() if k not in ("ts",)}
        ctl = self._record_task("tacit.control", sender=sender, task_input={"control": method, **clean})
        cp: dict[str, Any] = {"from": sender, "task_id": ctl, "reason": params.get("reason") or method}
        if method == "control.supersede":
            cp["successor_task"] = {"kind": "tacit.fragment",
                                    "input": {"supersedes": params.get("supersedes"),
                                              "by_fragment": params.get("by_fragment")},
                                    "assignee": sender}
        self._dispatch(method, **cp)
        return _Entry(seq=self._last_seq())

    # ---- queries ---------------------------------------------------------------
    def artefacts_of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [a for a in self.artefacts.values() if a["kind"] == kind]

    def evidence_records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in self.chain.entries:
            env = e.envelope
            p = env.get("params") or {}
            out.append({
                "seq": e.seq,
                "workspace": self.workspace_id,
                "method_or_type": env.get("method"),
                "from": p.get("from"),
                "prev_hash": getattr(e, "prev_hash", None),
                "envelope": env,
            })
        return out

    def descriptor(self) -> dict[str, Any]:
        ws = self.coord.get_workspace(self.workspace_id)
        members = [{"uri": m.uri, "role": m.role} for m in ws.members.values()] if ws else self.members
        return {
            "id": self.workspace_id,
            "name": self.name,
            "created": ws.created if ws else self.now_iso(),
            "state": ws.state if ws else "active",
            "mode": ws.mode if ws else self.mode,
            "mode_ceiling": ws.mode_ceiling if ws else self.mode_ceiling,
            "coordinator": self.coordinator,
            "members": members,
            "profiles": ws.profiles if ws else self.profiles,
            "evidence_head": (ws.chain_head if ws and ws.chain_head else ZERO_HASH),
            "evidence_count": len(ws.audit) if ws else self.chain.count,
        }

    def verify(self) -> VerificationResult:
        return self.chain.verify()
