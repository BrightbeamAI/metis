"""MemoryBroker, assembles an AgentMemoryContext from the four memory stores.

The broker is how an AI agent uses tacit memory alongside procedural, semantic, and
episodic memory. Tacit memory is queried only through the retrieval gate; blocked tacit
results go to the audit trail, with reasons, and stay out of the guidance.
"""
from __future__ import annotations

import datetime as _dt

from ..conditions.context import TacitContext
from ..fragment.store import FragmentStore
from ..retrieval.decision import BlockedItem, EligibleItem, RetrievalDecision
from ..retrieval.escalation import escalation_actions, open_escalation
from ..retrieval.gate import RetrievalGate
from .agent_context import (
    AgentMemoryContext,
    BlockedTacitMemory,
    TacitMemoryEntry,
)
from .episodic import EpisodicMemoryStore
from .procedural import ProceduralMemoryStore
from .semantic import SemanticMemoryStore
from .tacit import TacitMemoryStore

_ACTION_HINTS = ("confirm", "ask", "escalate", "human", "verify", "do not automatically")
_DEFAULT_NOTES = [
    "Tacit memory is governed, situated guidance that holds under its recorded conditions.",
    "Respect every use constraint and the conditions of applicability.",
    "Blocked tacit results stay out of the guidance; each one is recorded for audit.",
]


class MemoryBroker:
    def __init__(
        self,
        *,
        procedural: ProceduralMemoryStore,
        semantic: SemanticMemoryStore,
        episodic: EpisodicMemoryStore,
        fragment_store: FragmentStore,
        tacit_store: TacitMemoryStore,
        gate: RetrievalGate | None = None,
        adapter=None,
        escalation_assignee: str | None = None,
    ) -> None:
        self.escalation_assignee = escalation_assignee
        self.procedural = procedural
        self.semantic = semantic
        self.episodic = episodic
        self.fragment_store = fragment_store
        self.tacit_store = tacit_store
        self.gate = gate or RetrievalGate()
        self.adapter = adapter

    def query(
        self,
        task_id: str,
        context: TacitContext,
        *,
        role: str | None = None,
        now: _dt.datetime | None = None,
        emit: bool = False,
        requester: str | None = None,
    ) -> AgentMemoryContext:
        ctx = AgentMemoryContext(
            task_id=task_id,
            runtime_context=context.model_dump(mode="json", exclude_none=True),
            governance_notes=list(_DEFAULT_NOTES),
        )
        ctx.procedural_memory = self.procedural.query(context)
        ctx.semantic_memory = self.semantic.query(context)
        ctx.episodic_memory = self.episodic.query(context)

        required_actions: list[str] = []
        for mo in self.tacit_store.all():
            fragment = self.fragment_store.get(mo.fragment_id)
            if fragment is None:
                ctx.blocked_tacit_memory.append(
                    BlockedTacitMemory(memory_id=mo.memory_id, fragment_id=mo.fragment_id,
                                       reason="revoked_or_superseded", detail="source fragment not found"))
                continue
            el = self.gate.evaluate(fragment, context, role=role, now=now)
            if el.ok:
                citations = [f"evidence:{s}" for s in mo.linked_chap_evidence_refs]
                citations += fragment.provenance.source_artefacts
                ctx.tacit_memory.append(TacitMemoryEntry(
                    memory_id=mo.memory_id,
                    fragment_id=mo.fragment_id,
                    authority_layer=mo.authority_layer.value,
                    content=mo.content,
                    use_constraints=mo.use_constraints,
                    citations=citations,
                    audit_refs=mo.linked_chap_evidence_refs,
                ))
                ctx.citations.extend(citations)
                ctx.audit_refs.extend(mo.linked_chap_evidence_refs)
                for c in mo.use_constraints:
                    if any(h in c.lower() for h in _ACTION_HINTS):
                        required_actions.append(c)
            else:
                ctx.blocked_tacit_memory.append(BlockedTacitMemory(
                    memory_id=mo.memory_id, fragment_id=mo.fragment_id,
                    reason=el.reason.value if el.reason else "unknown", detail=el.detail,
                    escalate=el.escalate))

        escalated = [b for b in ctx.blocked_tacit_memory if b.escalate]
        if emit and self.adapter is not None and self.escalation_assignee and escalated:
            ctx.escalation_task_id = open_escalation(
                self.adapter, requester=requester or self.adapter.coordinator,
                assignee=self.escalation_assignee, runtime_context=ctx.runtime_context,
                items=escalated, origin_task=task_id)
        required_actions.extend(escalation_actions(escalated, ctx.escalation_task_id))

        # de-duplicate while preserving order
        seen: set[str] = set()
        for a in required_actions:
            if a not in seen:
                seen.add(a)
                ctx.required_human_actions.append(a)

        if emit and self.adapter is not None:
            self._record_decision(task_id, ctx, requester or self.adapter.coordinator)
        return ctx

    def _record_decision(self, task_id: str, ctx: AgentMemoryContext, requester: str) -> None:
        decision = RetrievalDecision(
            requested_role=None,
            runtime_context=ctx.runtime_context,
            eligible=[EligibleItem(fragment_id=t.fragment_id, memory_id=t.memory_id,
                                   authority_layer=t.authority_layer, use_constraints=t.use_constraints)
                      for t in ctx.tacit_memory],
            blocked=[BlockedItem(fragment_id=b.fragment_id or "", memory_id=b.memory_id,
                                 reason=b.reason, detail=b.detail, escalate=b.escalate)
                     for b in ctx.blocked_tacit_memory],
            escalation_task_id=ctx.escalation_task_id,
            required_human_actions=escalation_actions(
                [b for b in ctx.blocked_tacit_memory if b.escalate], ctx.escalation_task_id),
            rationale="MemoryBroker condition-aware retrieval.",
        )
        self.adapter.append_artefact(
            "tacit.retrieval_decision", produced_by=requester,
            content=decision.model_dump(mode="json"), task=task_id)
        art = self.adapter.append_artefact(
            "tacit.agent_memory_context", produced_by=requester,
            content=ctx.model_dump(mode="json"), task=task_id)
        ctx.audit_refs.append(self.adapter.artefact_evidence[art])
