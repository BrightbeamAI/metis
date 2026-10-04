# Condition-aware retrieval

The retrieval gate is one of the most important parts of Metis. It asks one question: "is this
fragment *allowed* to be used in this situation?" The answer comes from the fragment's recorded
conditions, consent, and authority, checked in a fixed order.

## Why conditions come first

A fragment is bound to the conditions under which a judgement was made. A cue that is valid for a
centrifugal pump under high load at pre-alarm may be irrelevant, or unsafe, for a gear pump at
startup, however alike the two situations read. The gate returns a fragment only when its
structured conditions are satisfied, and it fails closed: an unknown runtime value counts as a
mismatch.

## The checks (in priority order)

The gate (`retrieval/gate.py`) evaluates the checks in this order and returns the first failing
reason:

1. revocation status is active;
2. consent permits use;
3. endogenous fragments have passed Mission Group review;
4. the authority layer permits use (Evidence is blocked);
5. the validation state permits use (Tier-2 promoted);
6. the review date has not passed;
7. the requesting role is authorised;
8. the structured conditions match, the validity window is open (an elapsed window reports
   `expired_review_date`), and no exclusion applies;
9. for Controlled fragments, the match is exact and fully specified;
10. the risk class does not require a person to decide.

Applicability (checks 8 and 9) comes before risk (check 10). A fragment written for a different
machine is reported with the condition that failed, so a high-risk query brings a person only the
fragments that apply, plus the near misses.

## Escalation to a person

Two kinds of blocked result go to a person. The gate flags them with `escalate = true`:

- **High risk.** The fragment applies, and the situation's risk class (`high` or `critical` by
  default) calls for human judgement.
- **Near miss.** The fragment's identity conditions (site, area, line, equipment, product, material
  lot) all match, and a situational condition fails: a different operating mode, shift, or trigger,
  an unknown value, or an exclusion. This is where an agent would be tempted to apply guidance
  outside its envelope. A role mismatch is a plain block, with no escalation.

When a recorded retrieval or memory query contains escalated items, Metis opens one
`tacit.escalation` CHAP task for the person on duty (the operator by default,
`MetisEngine.escalation_assignee`; on the server, the workspace's escalation group), records its id
on the decision, and adds a required human action to the agent's context. The agent receives that
action and waits for the person's decision.

The person records it with `MetisEngine.decide_escalation`, which completes the task with a
`tacit.escalation_decision`: the guidance `applies` in this situation, it `does_not_apply`, or
the Mission Group should look again (`refer_to_review`, which opens a review of each fragment).
The decision covers that situation only; what a fragment may do in general stays with the
reviewers.

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
is recorded as a CHAP evidence entry. The gate is deterministic, and a local model plays no part in
eligibility.
