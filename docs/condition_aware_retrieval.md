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

The gate (`retrieval/gate.py`) evaluates the checks in this order and returns the first failing
reason:

1. revocation status is active;
2. consent permits use;
3. endogenous fragments have passed Mission Group review;
4. the authority layer permits use (Evidence is blocked);
5. the validation state permits use (Tier-2 promoted);
6. the review date and validity window have not elapsed;
7. the requesting role is authorised;
8. the structured conditions match and no exclusion applies;
9. for Controlled fragments, the match is exact and fully specified;
10. the risk class does not require a person to decide.

Applicability (checks 8 and 9) comes before risk (check 10). A fragment written for a different
machine is reported as not applying, never as an escalation, so a high-risk query does not flood a
person with fragments that were never relevant.

## Escalation to a person

Some blocked results need a person rather than silence. The gate flags two cases with
`escalate = true`:

- **High risk.** The fragment applies, but the situation's risk class (`high` or `critical` by
  default) calls for human judgement.
- **Near miss.** The fragment's identity conditions (site, area, line, equipment, product, material
  lot) all match, but a situational condition fails: a different operating mode, shift, or trigger,
  an unknown value, or an exclusion. This is where an agent would be tempted to apply guidance
  outside its envelope. An unauthorised role is blocked, not escalated.

When a recorded retrieval or memory query contains escalated items, Metis opens one
`tacit.escalation` CHAP task for the person on duty (the operator by default,
`MetisEngine.escalation_assignee`), records its id on the decision, and adds a required human action
to the agent's context. The agent receives the action, not the guidance.

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

Every recorded retrieval attempt, whether anything is returned or not, produces a
`tacit.retrieval_decision` artefact listing eligible items (with their use constraints), blocked
items (with reasons and escalation flags), any escalation task, and the required human actions. It
is recorded as a CHAP evidence entry. A local model never decides eligibility.
