# Governance model

Metis's governance is deterministic and human-reviewed. A local model may draft text, but it
never makes a governance decision.

## Capture Cell, Mission Group, Runtime Orchestrator

A **Capture Cell** is the local setting where capture happens, a CHAP workspace with an operator
(human), a whisperer (agent), a Mission Group (group), and a coordinator/Runtime Orchestrator
(service). The **Mission Group** performs Tier-2 validation as a CHAP group participant. The
**Runtime Orchestrator** is the CHAP coordinator plus routing/control/modes capabilities; it governs
retrieval and lifecycle at runtime.

## The three authority layers

The **Evidence layer** holds raw observations, worker confirmations, early hypotheses, rejected
fragments, and unvalidated fragments. It may support learning and review, but it must not influence
operational decisions, is blocked by the retrieval gate, and can never become agent-visible tacit
memory.

The **Advisory layer** holds Tier-2 validated fragments offered as conditional decision support.
Advisory fragments are retrievable only when conditions match, are presented as situated guidance
rather than universal rules, and carry provenance, confidence, and use constraints. They may become
agent-visible advisory context.

The **Controlled layer** holds fragments formally incorporated into procedures or controlled
knowledge bases. Controlled promotion requires change-control metadata, stricter (exact) condition
matching, and review/expiry metadata, and preserves full audit lineage. Controlled fragments may
become controlled instruction only when policy allows.

## Tier-1 and Tier-2

**Tier-1 confirmation** concerns descriptive fidelity only: did the system faithfully represent what
the worker meant or did? It does not decide whether the fragment should influence future work.
**Tier-2 review** is the Mission Group's judgement over description fidelity, operational relevance,
normative alignment, safety/quality/compliance/fairness/surveillance risk, evidence strength,
recurrence, counterexamples, conditions, consent, and review/expiry.

## Lifecycle transitions

Promotion requires a Mission Group decision and a `tacit.promotion_record`. Rejection requires a
decision and a `tacit.rejection_record`; rejected fragments remain in the audit chain. Re-elicitation
requires a `tacit.re_elicitation_request`. Revocation requires a CHAP control event and a
`tacit.revocation_record`; supersession adds a `tacit.supersession_record`. Endogenous fragments can
never self-promote: they start in Evidence, require Mission Group review, and must clear a higher
evidence bar. Every transition is auditable through the CHAP evidence chain. A model cannot drive any
of these.
