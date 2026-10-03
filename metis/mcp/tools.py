"""The Metis tool surface for agents, with the governance contract built in.

Agents may read governed guidance, assemble a memory context, submit observations, and relay
a worker's own answers and contests. They may not review, promote, or authorise anything:
Tier-2 decisions stay with named human reviewers outside this surface. Usable guidance comes
only from ``retrieve_guidance`` and ``agent_memory_context``, which pass the condition-aware
gate and record the decision on the workspace's CHAP chain; listing tools return metadata,
never content, so nothing reaches an agent around the gate.

Every method returns plain JSON-safe data. This module does not depend on the MCP SDK.
"""
from __future__ import annotations

import threading
from typing import Any

from ..conditions.context import TacitContext
from ..consent.contestability import ContestAction
from ..consent.model import ConsentRecord, ConsentStatus
from ..engine import MetisEngine
from ..integrations.chap.participants import type_of
from ..project import Project
from ..retrieval.blocked_reasons import HUMAN_READABLE, BlockedReason
from ..taxonomy.categories import CATEGORY_META, AuthorityLayer, RevocationStatus

INSTRUCTIONS = (
    "Metis serves governed tacit memory: reviewed fragments of expert practice that apply only "
    "under recorded conditions. Before acting in a work situation, call retrieve_guidance with "
    "the current context. Treat guidance as situated and advisory, never as ground truth, and "
    "honour every use constraint. When required_human_actions is not empty, stop and involve the "
    "named person instead of acting. Never answer a whisper or contest a fragment on a worker's "
    "behalf: relay only what the worker said, under the worker's own identity."
)

# Blocked reasons that concern authorisation, not the situation. An agent learns only how many
# fragments were withheld for these reasons, not which.
_NOT_AUTHORISED = {
    BlockedReason.evidence_layer_not_authorised.value,
    BlockedReason.tier2_validation_missing.value,
    BlockedReason.endogenous_fragment_requires_review.value,
}
_RESPONSES = ("confirm", "correct", "dismiss", "defer")


def _explain(reason: str) -> str:
    try:
        return HUMAN_READABLE[BlockedReason(reason)]
    except ValueError:
        return reason


def _require_human(uri: str, what: str) -> None:
    if type_of(uri) != "human":
        raise PermissionError(f"{what} must be a human participant URI (human:...), got {uri!r}.")


def _context(data: dict[str, Any]) -> TacitContext:
    return TacitContext.model_validate({k: v for k, v in data.items() if v is not None})


class MetisTools:
    def __init__(self, project: Project, workspace_id: str | None = None) -> None:
        self.project = project
        self.workspace_id = workspace_id
        self._engine: MetisEngine | None = None
        self._lock = threading.RLock()

    @property
    def engine(self) -> MetisEngine:
        if self._engine is None:
            self._engine = self.project.open(self.workspace_id)
        return self._engine

    def _save(self) -> None:
        self.project.save(self.engine)

    def _withheld(self, blocked: list[Any]) -> tuple[list[dict[str, Any]], int]:
        shown, hidden = [], 0
        for item in blocked:
            if item.reason in _NOT_AUTHORISED:
                hidden += 1
                continue
            shown.append({"fragment_id": item.fragment_id, "reason": item.reason,
                          "explanation": _explain(item.reason), "detail": item.detail,
                          "a_person_decides": item.escalate})
        return shown, hidden

    # ---- read ----------------------------------------------------------------------
    def describe_workspace(self) -> dict[str, Any]:
        with self._lock:
            eng = self.engine
            layers: dict[str, int] = {}
            for f in eng.fragments.all():
                layers[f.authority_layer.value] = layers.get(f.authority_layer.value, 0) + 1
            chain = eng.verify()
            return {
                "workspace": eng.adapter.workspace_id,
                "name": eng.adapter.name,
                "fragments_by_authority_layer": layers,
                "agent_visible_memory": len(self._visible_memory()),
                "pending_whispers": len(eng.pending_captures),
                "mission_group_reviewers": eng.mission_group_members,
                "review_rule": eng.governance.policy.review_rule,
                "evidence_chain": {"entries": chain.checked, "verified": chain.ok},
            }

    def _visible_memory(self) -> list[Any]:
        eng = self.engine
        out = []
        for mo in eng.tacit_store.all():
            frag = eng.fragments.get(mo.fragment_id)
            if (frag is not None and mo.authority_layer != AuthorityLayer.evidence
                    and mo.revocation_status == RevocationStatus.active
                    and frag.consent.permits_retrieval()):
                out.append(mo)
        return out

    def list_tacit_memory(self) -> list[dict[str, Any]]:
        """Metadata of agent-visible tacit memory. Content comes only through retrieval."""
        with self._lock:
            return [{"memory_id": mo.memory_id, "fragment_id": mo.fragment_id, "title": mo.title,
                     "category": mo.category.value, "authority_layer": mo.authority_layer.value,
                     "conditions": {k: v for k, v in mo.conditions.items() if v not in (None, [], {})},
                     "review_due_at": mo.review_due_at}
                    for mo in self._visible_memory()]

    def list_pending_whispers(self, worker: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [{"whisper_id": p.whisper_id, "worker": p.worker, "question": p.whisper.question,
                     "options": [o["id"] for o in p.whisper.options],
                     "observation": p.observation.work_as_done or p.observation.text,
                     "candidate_category": p.candidate.category}
                    for p in self.engine.pending_captures.values()
                    if worker is None or p.worker == worker]

    def taxonomy(self) -> list[dict[str, Any]]:
        return [{"category": m.category.value, "label": m.label, "domain": m.domain.value,
                 "spender_quadrant": m.spender_quadrant, "capture_modality": m.capture_modality,
                 "loop_role": m.loop_role, "description": m.description}
                for m in CATEGORY_META.values()]

    # ---- governed retrieval ----------------------------------------------------------
    def retrieve_guidance(self, context: dict[str, Any], role: str | None = None) -> dict[str, Any]:
        with self._lock:
            eng = self.engine
            decision = eng.retrieve(_context(context), role=role)
            self._save()
            guidance = []
            for item in decision.eligible:
                mo = eng.tacit_store.get(item.memory_id) if item.memory_id else None
                frag = eng.fragments.get(item.fragment_id)
                guidance.append({
                    "fragment_id": item.fragment_id, "memory_id": item.memory_id,
                    "authority_layer": item.authority_layer,
                    "guidance": mo.content if mo else (frag.content if frag else ""),
                    "use_constraints": item.use_constraints, "confidence": item.confidence,
                })
            withheld, hidden = self._withheld(decision.blocked)
            return {
                "guidance": guidance,
                "withheld": withheld,
                "not_yet_authorised": hidden,
                "required_human_actions": decision.required_human_actions,
                "escalation_task_id": decision.escalation_task_id,
                "recorded_at_seq": eng.adapter.chain.count - 1,
                "note": "Situated, advisory guidance. Honour every use constraint; when "
                        "required_human_actions is not empty, a person decides.",
            }

    def agent_memory_context(self, task: str, context: dict[str, Any],
                             role: str | None = None) -> dict[str, Any]:
        with self._lock:
            amc = self.engine.agent_context(task, _context(context), role=role)
            self._save()
            withheld, hidden = self._withheld(amc.blocked_tacit_memory)
            return {
                "task": amc.task_id,
                "procedural": [{"source": e.source, "content": e.content} for e in amc.procedural_memory],
                "semantic": [{"source": e.source, "content": e.content} for e in amc.semantic_memory],
                "episodic": [{"source": e.source, "content": e.content} for e in amc.episodic_memory],
                "tacit": [{"memory_id": t.memory_id, "fragment_id": t.fragment_id,
                           "authority_layer": t.authority_layer, "guidance": t.content,
                           "use_constraints": t.use_constraints} for t in amc.tacit_memory],
                "withheld": withheld,
                "not_yet_authorised": hidden,
                "required_human_actions": amc.required_human_actions,
                "escalation_task_id": amc.escalation_task_id,
                "governance_notes": amc.governance_notes,
            }

    # ---- capture (the worker answers) ------------------------------------------------
    def submit_observation(self, observation_id: str, work_as_done: str, context: dict[str, Any],
                           worker: str, work_as_imagined: str | None = None,
                           category: str | None = None, title: str | None = None) -> dict[str, Any]:
        _require_human(worker, "worker")
        with self._lock:
            ctx = _context(context)
            pending = self.engine.begin_capture(
                {"observation_id": observation_id, "work_as_imagined": work_as_imagined,
                 "work_as_done": work_as_done, "context": ctx, "source": "mcp"},
                consent=ConsentRecord(consent_status=ConsentStatus.pending),
                worker=worker, category=category, title=title, conditions=ctx)
            self._save()
            if pending.deferred:
                return {"deferred": True, "reason": pending.deferred_reason,
                        "note": f"{worker} has reached the whisper budget; nothing was asked."}
            return {"deferred": False, "whisper_id": pending.whisper_id, "worker": worker,
                    "question": pending.whisper.question,
                    "options": [o["id"] for o in pending.whisper.options],
                    "candidate": {"category": pending.candidate.category,
                                  "hypothesis": pending.candidate.hypothesis},
                    "note": "A hypothesis only. Put the question to the worker and relay their "
                            "own answer with answer_whisper."}

    def answer_whisper(self, whisper_id: str, response: str, answered_by: str, consent: str,
                       corrected_text: str | None = None) -> dict[str, Any]:
        _require_human(answered_by, "answered_by")
        if response not in _RESPONSES:
            raise ValueError(f"response must be one of {', '.join(_RESPONSES)}")
        if consent not in ("granted", "declined"):
            raise ValueError("consent must be 'granted' or 'declined', as the worker stated it")
        with self._lock:
            result = self.engine.answer_whisper(
                whisper_id, response=response, answered_by=answered_by,
                corrected_content=corrected_text, consent_granted=(consent == "granted"))
            self._save()
            frag = result.fragment
            if frag is None:
                return {"stored": False,
                        "note": "The answer is recorded; no fragment was stored."}
            return {"stored": True, "fragment_id": frag.fragment_id,
                    "authority_layer": frag.authority_layer.value,
                    "validation_state": frag.validation_state.value,
                    "consent": frag.consent.consent_status.value,
                    "note": "Stored in the Evidence layer. It reaches agents only after a quorum "
                            "of Mission Group reviewers promotes it."}

    def contest_fragment(self, fragment_id: str, action: str, raised_by: str, rationale: str,
                         proposed_correction: str | None = None) -> dict[str, Any]:
        _require_human(raised_by, "raised_by")
        with self._lock:
            out = self.engine.governance.contest(
                fragment_id, ContestAction(action), raised_by=raised_by, rationale=rationale,
                proposed_correction=proposed_correction)
            self._save()
            return {"recorded": True, "action": action, **{k: v for k, v in out.items() if isinstance(v, str)}}

    # ---- audit -----------------------------------------------------------------------
    def audit_verify(self) -> dict[str, Any]:
        with self._lock:
            eng = self.engine
            result = eng.verify()
            ledger = eng.adapter.ledger
            return {"entries": result.checked, "verified": result.ok, "errors": result.errors,
                    "ledger_entries": ledger.count if ledger else None,
                    "ledger_agrees": (ledger.count == result.checked) if ledger else None}

    def audit_tail(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            records = self.engine.adapter.evidence_records()[-max(1, min(limit, 200)):]
            return [{"seq": r["seq"], "method": r["method_or_type"], "from": r["from"]} for r in records]
