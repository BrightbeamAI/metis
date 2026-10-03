# Governance model

Metis's governance is deterministic and human-reviewed. People make every governance decision; a
local model may draft text for them.

## Capture Cell, Mission Group, Runtime Orchestrator

A **Capture Cell** is the local setting where capture happens: a CHAP workspace, created by the
coordinator (a service), with an operator (human), a whisperer (agent), the Mission Group (group)
and its named reviewers, and an assistant agent. The **Mission Group** performs Tier-2 validation. It appears on the record as a CHAP
group participant, and its decisions are made by named human reviewers
(`MetisEngine.mission_group_members`). The **Runtime Orchestrator** is the CHAP coordinator plus the
retrieval gate, escalation, and whisper budget; it governs retrieval and lifecycle at runtime.

## Collective decisions

Granting authority is a collective decision. A Tier-2 review is addressed to every Mission Group
reviewer under the policy's review rule (`GovernancePolicy.review_rule`, `quorum:2` by default),
and the CHAP coordinator enforces it: a promotion completes only when enough distinct reviewers
approve, a repeated approval from one reviewer counts once, and only the reviewers the review was
addressed to can approve. Metis checks the promotion policy before it records any approval, so
every approval on the chain belongs to a promotion that policy allowed. The promotion record names
the approvers and the rule they satisfied.

Withholding authority needs one reviewer: any single reviewer can hold, reject, or ask for
re-elicitation, because each of these withholds use. A held fragment gets a fresh review when it
returns.

Callers pass the deciding reviewers as `decided_by`. When they omit it, the configured members are
used in order; that convenience suits demos and tests. A deployment passes authenticated reviewer
identities.

## Confidence, review dates, and expiry

A fragment's confidence grades its recorded evidence. It is computed from the evidence (strength,
number of cases, a linked outcome, counterexamples) by a documented rule in
`metis/fragment/confidence.py`, and recomputed at every Tier-2 review. The inference model's own
score stays on the candidate as a prior.

Promotion sets a review date: 180 days for Advisory and 365 for Controlled by default, halved for
high-risk fragments, plus descriptive expiry triggers (review date reached, procedure revised,
equipment or process change). After the review date the retrieval gate blocks the fragment with
`expired_review_date`. Reviewers renew the practice by superseding the fragment with a freshly
reviewed one.

## The three authority layers

The **Evidence layer** holds raw observations, worker confirmations, early hypotheses, rejected
fragments, and unvalidated fragments. It supports learning and review. The retrieval gate blocks
it, so it stays out of operational decisions and out of agent-visible tacit memory.

The **Advisory layer** holds Tier-2 validated fragments offered as conditional decision support.
Advisory fragments are retrievable only when conditions match, are presented as situated guidance
for their recorded conditions, and carry provenance, confidence, and use constraints. They may
become agent-visible advisory context.

The **Controlled layer** holds fragments formally incorporated into procedures or controlled
knowledge bases. Controlled promotion requires change-control metadata, stricter (exact) condition
matching, and review/expiry metadata, and preserves full audit lineage. Controlled fragments may
become controlled instruction only when policy allows.

## Tier-1 and Tier-2

**Tier-1 confirmation** concerns descriptive fidelity: did the system faithfully represent what the
worker meant or did? Whether the fragment should influence future work is a Tier-2 question.
**Tier-2 review** is the Mission Group's judgement over description fidelity, operational relevance,
normative alignment, safety/quality/compliance/fairness/surveillance risk, evidence strength,
recurrence, counterexamples, conditions, consent, and review/expiry.

## Contestability

Workers and reviewers can contest a fragment at any time, and each contest is recorded first as a
`tacit.validation_event`. A challenge, correction, or proposed supersession opens a fresh
`tacit.validate.tier2` task for the Mission Group; a re-elicitation request opens a
`tacit.re_elicit` task. The reviewers answer a contest on an unpromoted fragment through its Tier-2
review, and a contest on a promoted fragment by keeping, revoking, or superseding it. Withdrawal
belongs to the worker who contributed the fragment: it withdraws consent and revokes the fragment.
Reviewers retire a fragment through revocation.

## Lifecycle transitions

Promotion requires a quorum decision of the Mission Group and a `tacit.promotion_record`. Rejection
requires a decision and a `tacit.rejection_record`; rejected fragments remain in the audit chain.
Re-elicitation requires a `tacit.re_elicitation_request`. Revocation requires a CHAP control event
and a `tacit.revocation_record`; supersession adds a `tacit.supersession_record`. Endogenous
fragments can never self-promote: they start in Evidence, require Mission Group review, and must
clear a higher evidence bar. Every transition is auditable through the CHAP evidence chain, and
people drive every one of them.
