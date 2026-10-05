"""The Metis tool surface for agents, with the governance contract built in.

Agents may read governed guidance, assemble a memory context, submit observations, and relay
a worker's own answers and contests. Review, promotion, and authorisation stay with named
human reviewers outside this surface. Usable guidance comes
only from ``retrieve_guidance`` and ``agent_memory_context``, which pass the condition-aware
gate and record the decision on the workspace's CHAP chain. Listing tools return metadata
only, so every piece of content an agent sees has passed the gate.

Every method returns plain JSON-safe data. This module does not depend on the MCP SDK.
"""
from __future__ import annotations

import threading
from typing import Any

from .. import guidance as views
from ..consent.contestability import ContestAction
from ..consent.model import ConsentRecord, ConsentStatus
from ..engine import MetisEngine
from ..integrations.chap.participants import type_of
from ..project import Project
from ..taxonomy.categories import CATEGORY_META
from ..validation.states import InvalidTransition

INSTRUCTIONS = (
    "Metis serves governed tacit memory: reviewed fragments of expert practice that apply only "
    "under recorded conditions. Before acting in a work situation, call retrieve_guidance with "
    "the current context, including its risk class. Treat guidance as situated advice for "
    "those conditions, and honour every use constraint. When required_human_actions lists "
    "anything, stop and hand the decision to a person. Relay a worker's answers and contests "
    "in the worker's own words, under the worker's own identity."
)

_RESPONSES = ("confirm", "correct", "dismiss", "defer")


def _require_human(uri: str, what: str) -> None:
    if type_of(uri) != "human":
        raise PermissionError(f"{what} must be a human participant URI (human:...), got {uri!r}.")


_context = views.context_from


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
        return views.withheld(self.engine, blocked)

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
        return views.visible_memory(self.engine)

    def list_tacit_memory(self) -> list[dict[str, Any]]:
        """Metadata of agent-visible tacit memory. Content comes only through retrieval."""
        with self._lock:
            return views.memory_listing(self.engine)

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
        """Governed guidance for a work situation, which must name its risk class."""
        with self._lock:
            decision = self.engine.retrieve(views.agent_situation(context), role=role)
            self._save()
            return views.guidance_view(self.engine, decision)

    def agent_memory_context(self, task: str, context: dict[str, Any],
                             role: str | None = None) -> dict[str, Any]:
        with self._lock:
            amc = self.engine.agent_context(task, views.agent_situation(context), role=role)
            self._save()
            return views.agent_context_view(self.engine, amc)

    # ---- capture (the worker answers) ------------------------------------------------
    def submit_observation(self, observation_id: str, work_as_done: str, context: dict[str, Any],
                           worker: str, work_as_imagined: str | None = None,
                           category: str | None = None, title: str | None = None) -> dict[str, Any]:
        """Start a capture: infer a candidate and whisper one question to ``worker``.

        Reporting the same observation again (a retry) returns the whisper it raised, so a retry
        never asks the worker twice; another observation under a recorded id is refused."""
        _require_human(worker, "worker")
        with self._lock:
            ctx = _context(context)
            eng = self.engine
            if eng.observation_seen(observation_id):
                same = next((c for c in eng.pending_captures.values()
                             if c.observation.observation_id == observation_id), None)
                if (same is not None and same.worker == worker
                        and same.observation.work_as_done == work_as_done):
                    return {"deferred": False, "repeated": True, **self._asked(same)}
                raise InvalidTransition(f"Observation {observation_id} was reported already; "
                                        "give a new observation a new id.")
            pending = eng.begin_capture(
                {"observation_id": observation_id, "work_as_imagined": work_as_imagined,
                 "work_as_done": work_as_done, "context": ctx, "source": "mcp"},
                consent=ConsentRecord(consent_status=ConsentStatus.pending),
                worker=worker, category=category, title=title, conditions=ctx)
            self._save()
            if pending.deferred:
                return {"deferred": True, "reason": pending.deferred_reason,
                        "note": f"{worker} has reached the whisper budget; nothing was asked."}
            return {"deferred": False, **self._asked(pending)}

    @staticmethod
    def _asked(pending: Any) -> dict[str, Any]:
        return {"whisper_id": pending.whisper_id, "worker": pending.worker,
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
        if response == "correct" and not (corrected_text or "").strip():
            raise ValueError("A correct answer needs the worker's corrected account in "
                             "corrected_text, in their own words.")
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
                    "ledger_agrees": ledger.matches(eng.adapter) if ledger else None}

    def audit_tail(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            records = self.engine.adapter.evidence_records()[-max(1, min(limit, 200)):]
            return [{"seq": r["seq"], "method": r["method_or_type"], "from": r["from"]} for r in records]
