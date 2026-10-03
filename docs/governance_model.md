# Governance model

Metis's governance is deterministic and human-reviewed. A local model may draft text, but it
never makes a governance decision.

## Capture Cell, Mission Group, Runtime Orchestrator

A **Capture Cell** is the local setting where capture happens, a CHAP workspace with an operator
(human), a whisperer (agent), a Mission Group (group), and a coordinator/Runtime Orchestrator
(service). The **Mission Group** performs Tier-2 validation. It appears on the record as a CHAP
group participant, and its decisions are made by named human reviewers
(`MetisEngine.mission_group_members`). The **Runtime Orchestrator** is the CHAP coordinator plus the
retrieval gate, escalation, and whisper budget; it governs retrieval and lifecycle at runtime.

## Collective decisions

Granting authority is a collective decision. A Tier-2 review is addressed to every Mission Group
reviewer under the policy's review rule (`GovernancePolicy.review_rule`, `quorum:2` by default),
and the CHAP coordinator enforces it: a promotion completes only when enough distinct reviewers
approve, a repeated approval from one reviewer counts once, and someone who was not addressed as a
reviewer cannot approve. Metis checks the same rule before it records anything, so the chain never
shows approvals for a promotion that policy then blocked. The promotion record names the approvers
and the rule they satisfied.

Withholding authority needs one reviewer: any single reviewer can hold, reject, or ask for
re-elicitation, because these never grant use. A held fragment gets a fresh review when it returns.

Callers pass the deciding reviewers as `decided_by`. When they omit it, the configured members are
used in order; that convenience suits demos and tests. A deployment passes authenticated reviewer
identities.

## Confidence, review dates, and expiry

A fragment's confidence grades its evidence, never a model's opinion. It is computed from the
recorded evidence (strength, number of cases, a linked outcome, counterexamples) by a documented
rule in `metis/fragment/confidence.py`, and recomputed at every Tier-2 review. The inference
model's own score stays on the candidate as a prior.

Promotion sets a review date: 180 days for Advisory and 365 for Controlled by default, halved for
high-risk fragments, plus descriptive expiry triggers (review date reached, procedure revised,
equipment or process change). After the review date the retrieval gate blocks the fragment with
`expired_review_date` until reviewers look at it again.

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
