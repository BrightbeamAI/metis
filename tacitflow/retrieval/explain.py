"""Human-readable explanation of a retrieval decision."""
from __future__ import annotations

from .blocked_reasons import HUMAN_READABLE, BlockedReason
from .decision import RetrievalDecision


def explain(decision: RetrievalDecision) -> str:
    lines = [f"Retrieval decision ({decision.policy_id}), {decision.rationale}", ""]
    if decision.eligible:
        lines.append("ELIGIBLE:")
        for item in decision.eligible:
            lines.append(f"  - {item.fragment_id} [{item.authority_layer}] conf={item.confidence:.2f}")
            for c in item.use_constraints:
                lines.append(f"      constraint: {c}")
    if decision.blocked:
        lines.append("BLOCKED:")
        for item in decision.blocked:
            try:
                why = HUMAN_READABLE[BlockedReason(item.reason)]
            except ValueError:
                why = item.reason
            lines.append(f"  - {item.fragment_id}: {item.reason}, {why} ({item.detail})")
    return "\n".join(lines)


def explain_reason(reason: str) -> str:
    try:
        return HUMAN_READABLE[BlockedReason(reason)]
    except ValueError:
        return reason
