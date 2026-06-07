"""routing/1.0 profile helpers.

Retrieval and escalation decisions are recorded using CHAP's routing capability shape
(``route_decision`` content: decision_type, outcome, policy_id, hints_observed, rationale).
TacitFlow's retrieval gate emits a ``tacit.retrieval_decision`` artefact carrying this
structure so decisions are deterministic and replayable from the audit log.
"""
from __future__ import annotations

from typing import Any

TASK_ROUTE = "task.route"
REVIEW_DEPTH = "review.depth"
ESCALATE_AUTO = "escalate.auto"


def route_decision_content(*, decision_type: str, outcome: Any, policy_id: str,
                           hints_observed: dict[str, Any], rationale: str) -> dict[str, Any]:
    return {
        "decision_type": decision_type,
        "outcome": outcome,
        "policy_id": policy_id,
        "hints_observed": hints_observed,
        "rationale": rationale,
    }
