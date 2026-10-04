"""What an agent is shown: governed guidance, withheld items, and visible memory.

These views are shared by every agent-facing surface (the MCP server and the HTTP server), so
each applies the same rules. Usable guidance comes only from a retrieval decision, which has
passed the condition-aware gate and is recorded on the CHAP chain. Listings carry metadata
only. A fragment that never reached an operational layer is counted, never named.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from . import clock
from .conditions.context import TacitContext
from .retrieval.blocked_reasons import HUMAN_READABLE, BlockedReason
from .taxonomy.categories import AuthorityLayer

# Blocked reasons that concern authorisation. For these an agent learns only how many
# fragments were withheld; their identities stay hidden.
NOT_AUTHORISED = {
    BlockedReason.evidence_layer_not_authorised.value,
    BlockedReason.tier2_validation_missing.value,
    BlockedReason.endogenous_fragment_requires_review.value,
}

GUIDANCE_NOTE = ("Situated, advisory guidance. Honour every use constraint; when "
                 "required_human_actions lists anything, a person decides.")


def explain(reason: str) -> str:
    try:
        return HUMAN_READABLE[BlockedReason(reason)]
    except ValueError:
        return reason


def overdue(fragment: Any, now: _dt.datetime) -> bool:
    if not fragment.review_due_at:
        return False
    due = _dt.datetime.fromisoformat(fragment.review_due_at.replace("Z", "+00:00"))
    return now > (due if due.tzinfo else due.replace(tzinfo=_dt.timezone.utc))


def context_from(data: dict[str, Any]) -> TacitContext:
    """A caller's context, within the size limits, as a ``TacitContext``."""
    from .limits import check_context

    check_context(data)
    return TacitContext.model_validate({k: v for k, v in data.items() if v is not None})


def withheld(engine: Any, blocked: list[Any]) -> tuple[list[dict[str, Any]], int]:
    """Blocked items an agent may see, and a count of those it may not."""
    shown, hidden = [], 0
    for item in blocked:
        frag = engine.fragments.get(item.fragment_id) if item.fragment_id else None
        unreviewed = frag is not None and frag.authority_layer == AuthorityLayer.evidence
        if item.reason in NOT_AUTHORISED or unreviewed:
            hidden += 1
            continue
        shown.append({"fragment_id": item.fragment_id, "reason": item.reason,
                      "explanation": explain(item.reason), "detail": item.detail,
                      "a_person_decides": item.escalate})
    return shown, hidden


def visible_memory(engine: Any) -> list[Any]:
    """Memory whose fragment is in use now: promoted, active, consented, and inside its
    review date. A held, rejected, re-eliciting, or overdue fragment drops out until the
    reviewers reinstate or renew it."""
    now = clock.now_dt()
    out = []
    for mo in engine.tacit_store.all():
        frag = engine.fragments.get(mo.fragment_id)
        if (frag is not None and frag.is_operationally_usable()
                and frag.consent.permits_retrieval() and not overdue(frag, now)):
            out.append(mo)
    return out


def memory_listing(engine: Any) -> list[dict[str, Any]]:
    """Metadata of agent-visible tacit memory. Content comes only through retrieval."""
    return [{"memory_id": mo.memory_id, "fragment_id": mo.fragment_id, "title": mo.title,
             "category": mo.category.value, "authority_layer": mo.authority_layer.value,
             "conditions": {k: v for k, v in mo.conditions.items() if v not in (None, [], {})},
             "review_due_at": mo.review_due_at}
            for mo in visible_memory(engine)]


def guidance_view(engine: Any, decision: Any) -> dict[str, Any]:
    """An agent's view of a retrieval decision."""
    guidance = []
    for item in decision.eligible:
        mo = engine.tacit_store.get(item.memory_id) if item.memory_id else None
        frag = engine.fragments.get(item.fragment_id)
        guidance.append({
            "fragment_id": item.fragment_id, "memory_id": item.memory_id,
            "authority_layer": item.authority_layer,
            "guidance": mo.content if mo else (frag.content if frag else ""),
            "use_constraints": item.use_constraints, "confidence": item.confidence,
        })
    shown, hidden = withheld(engine, decision.blocked)
    return {
        "guidance": guidance,
        "withheld": shown,
        "not_yet_authorised": hidden,
        "required_human_actions": decision.required_human_actions,
        "escalation_task_id": decision.escalation_task_id,
        "recorded_at_seq": engine.adapter.chain.count - 1,
        "note": GUIDANCE_NOTE,
    }


def agent_context_view(engine: Any, amc: Any) -> dict[str, Any]:
    """An agent's view of an assembled memory context."""
    shown, hidden = withheld(engine, amc.blocked_tacit_memory)
    return {
        "task": amc.task_id,
        "procedural": [{"source": e.source, "content": e.content} for e in amc.procedural_memory],
        "semantic": [{"source": e.source, "content": e.content} for e in amc.semantic_memory],
        "episodic": [{"source": e.source, "content": e.content} for e in amc.episodic_memory],
        "tacit": [{"memory_id": t.memory_id, "fragment_id": t.fragment_id,
                   "authority_layer": t.authority_layer, "guidance": t.content,
                   "use_constraints": t.use_constraints} for t in amc.tacit_memory],
        "withheld": shown,
        "not_yet_authorised": hidden,
        "required_human_actions": amc.required_human_actions,
        "escalation_task_id": amc.escalation_task_id,
        "governance_notes": amc.governance_notes,
    }
