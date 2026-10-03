"""Evidence-derived confidence for tacit fragments.

Confidence grades how strongly the recorded evidence supports a fragment: low after a single
observation, higher as the same pattern recurs with a linked outcome and without
counterexamples. It is computed deterministically from ``FragmentEvidence``, never from a
model's own score; a model's prior stays on the inference candidate. Confidence informs
review. It never grants permission to use a fragment; authority and the retrieval gate do.

Rule (clamped to [0.05, 0.95], two decimals):

- start from the evidence strength: none 0.10, weak 0.25, moderate 0.45, strong 0.65;
- add 0.04 for each recorded case beyond the first, up to six more (+0.24);
- add 0.05 when the fragment is linked to an outcome;
- subtract 0.08 for each counterexample, up to four (-0.32).
"""
from __future__ import annotations

from .model import EvidenceStrength, FragmentEvidence

_BASE = {
    EvidenceStrength.none: 0.10,
    EvidenceStrength.weak: 0.25,
    EvidenceStrength.moderate: 0.45,
    EvidenceStrength.strong: 0.65,
}


def evidence_confidence(evidence: FragmentEvidence) -> float:
    cases = max(evidence.recurrence_count, len(evidence.supporting_cases), 1)
    score = _BASE[evidence.evidence_strength]
    score += 0.04 * (min(cases, 7) - 1)
    if evidence.outcome_link:
        score += 0.05
    score -= 0.08 * min(len(evidence.counterexamples), 4)
    return round(min(max(score, 0.05), 0.95), 2)
