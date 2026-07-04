# Condition-aware retrieval

The retrieval gate is one of the most important parts of Metis. It is **not** semantic search.
It does not ask "which fragment is most similar to this situation?" It asks "is this fragment
*allowed* to be used in this situation?"

## Why semantic search is not enough

A fragment is bound to the conditions under which a judgement was made. A cue that is valid for a
centrifugal pump under high load at pre-alarm may be irrelevant, or unsafe, for a gear pump at
startup. Semantic similarity would happily return the fragment anyway. Metis's gate refuses
unless the structured conditions are satisfied, and it fails closed: an unknown runtime value never
counts as a match.

## The checks (in priority order)

The gate (`retrieval/gate.py`) evaluates, and returns the first failing reason: revocation status is
active; consent permits use; endogenous fragments have passed review; the authority layer permits use
(Evidence is blocked); the validation state permits use (Tier-2 promoted); the review date/validity
window has not elapsed; the requesting role is authorised; the risk class does not require human
escalation; the structured conditions match; no exclusion condition applies; and, for Controlled
fragments, the match is exact and fully specified.

## Blocked reasons

```
evidence_layer_not_authorised      tier2_validation_missing
conditions_do_not_match            expired_review_date
consent_withdrawn                  controlled_layer_requires_exact_match
risk_class_requires_human_escalation  endogenous_fragment_requires_review
revoked_or_superseded              role_not_authorised
exclusion_condition_applies
```

## What retrieval produces

Every retrieval attempt, whether anything is returned or not, produces a `tacit.retrieval_decision`
artefact listing eligible items (with their use constraints) and blocked items (with reasons), and is
recorded as a CHAP evidence entry. A local model never decides eligibility.
