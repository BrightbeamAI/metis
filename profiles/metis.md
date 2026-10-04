# Profile: `metis`

**Profile id:** `metis/1.0` · **Depends on:** CHAP Core, `review/1.0`, `whisper/1.0`, `control/1.0` · Metis workspaces also declare `routing/1.0`, `handoff/1.0`, and `modes/1.0`

The `metis/1.0` profile defines Metis-specific **task kinds**, **artefact kinds**,
metadata conventions, validation states, authority layers, consent rules, revocation rules,
memory-object rules, model-assist rules, and retrieval rules for governed tacit fragment
capture.

The profile leaves **CHAP Core unchanged**. It extends CHAP only through declared artefact kinds,
task kinds, metadata conventions, and validation rules, and it uses CHAP's own envelope, wire
methods, and evidence chain. Every Metis action is carried by an existing CHAP method
(`task.create` / `task.complete`, `whisper.ask` / `whisper.answer`, `review.request` with
`decide.approve`, `decide.reject`, `abstain.declare`, and `escalate.raise`, and `control.cancel` /
`control.supersede`) and recorded in the standard CHAP evidence chain.

---

## 1. Task kinds

Tasks the reference implementation opens:

| Kind | Opened for | Assigned to |
|------|------------|-------------|
| `tacit.capture` | one capture: observation, inference, whisper, and confirmation; the fragment's first Tier-2 review runs on it | the whisperer agent |
| `tacit.validate.tier2` | a fresh Mission Group review: when a held fragment returns, or when a fragment in use is re-reviewed (a contest, a renewal, or a reviewer's request) | the Mission Group |
| `tacit.re_elicit` | a re-elicitation decided at Tier-2 | the deciding reviewer |
| `tacit.retrieve` | one retrieval through the gate | the requesting agent |
| `tacit.escalation` | a decision handed to a person: a high-risk situation or a near miss | the operator by default |

Record tasks: every artefact except the whisper prompt, which travels in `whisper.ask`, is
recorded as a task whose kind is the artefact kind, completed with the artefact as its output.
`tacit.control` records the parameters of a `control.*` event.

Declared for implementations that model further steps as separate tasks, and used as participant
capability names (the whisperer advertises `tacit.infer` and `tacit.whisper`; the assistant agent
advertises `tacit.memory.query`):

```
tacit.infer            tacit.whisper          tacit.confirm
tacit.validate.tier1   tacit.promote          tacit.reject
tacit.hold             tacit.memory.prepare   tacit.memory.query
tacit.model.assist     tacit.revoke           tacit.supersede
tacit.export_audit
```

## 2. Artefact kinds

Each non-standard kind carries a `schema` reference
(`https://metis.dev/schemas/0.1/<kind>.schema.json`, with the kind's dots written as underscores,
for example `tacit_fragment.schema.json`), exactly as CHAP requires for implementation-defined
artefact kinds.

```
tacit.fragment              tacit.memory_object         tacit.agent_memory_context
tacit.capture_observation   tacit.inference_candidate   tacit.whisper_prompt
tacit.whisper_response      tacit.operator_confirmation tacit.validation_event
tacit.review_decision       tacit.promotion_record      tacit.rejection_record
tacit.re_elicitation_request tacit.retrieval_decision   tacit.revocation_record
tacit.supersession_record   tacit.consent_record        tacit.model_assist_record
```

JSON Schemas for the core kinds are published in [../schemas/](../schemas/): `tacit.fragment`,
`tacit.memory_object`, `tacit.agent_memory_context`, `tacit.retrieval_decision`,
`tacit.review_decision`, `tacit.promotion_record`, `tacit.revocation_record`,
`tacit.consent_record`, `tacit.validation_event`, and `tacit.model_assist_record`, plus
`tacit_context` for the conditions and runtime context they embed.

A `tacit.validation_event` names its `event`: `whisper_deferred` (the worker's prompt budget was
reached), `consent_declined` (the worker answered and withheld consent, so nothing was stored), or
`contestability` (a worker or reviewer contested a fragment).

## 3. Validation states

`captured → worker_confirmed → tier1_confirmed → tier2_pending →`
`{ promoted_to_advisory | promoted_to_controlled | held | rejected | re_elicit }`,
with terminal/lifecycle states `withdrawn`, `superseded`, `expired`. A promoted fragment is
re-reviewed in place: it keeps its state until the reviewers renew it, move it to the other
operational layer, hold it, reject it, or send it back for re-elicitation. A fragment awaiting
re-elicitation is replaced by a new capture that names it (`supersedes`): once the worker confirms
the replacement, `control.supersede` and a `tacit.supersession_record` link the two.

## 4. Authority layers

`evidence` (learning and review only; hidden from agents and from operational advice) ·
`advisory` (conditional decision support under matching conditions; agent-visible as context) ·
`controlled` (formally incorporated; change-control metadata + exact matching required).

## 5. Review rules

A Tier-2 review is a CHAP `review.request` addressed to every named Mission Group reviewer under
the policy's rule (`quorum:2` by default). Promotion needs that many distinct approvals, and Metis
promotes only a review CHAP has completed. One reviewer can hold (`abstain.declare`), reject
(`decide.reject`), or ask for re-elicitation (`escalate.raise`). Promotion sets a review date and
expiry triggers; the promotion record names the approvers and the rule.

A fragment in use goes back to review on a fresh `tacit.validate.tier2` task carrying a snapshot
of the fragment, opened by a contest, by a renewal, or at a reviewer's request. It stays in use
until the decision. Renewal and moves between Advisory and Controlled need the quorum, and a
later promotion rebuilds the fragment's memory object under the same memory id. Every contest
except a withdrawal joins the fragment's open review or opens one. A revoked fragment is out of
review, and a revocation or supersession cancels any review still open on it.

## 6. Retrieval rules

Tacit memory is retrieved only through the condition-aware gate. It checks, in order: revocation
status, consent, source pathway (endogenous fragments need review), authority layer, validation
state, review date, role, conditions with their validity window and exclusions, exact matching
for Controlled fragments, and risk class. Eligibility is decided deterministically from these
recorded properties. A high-risk situation, or a near miss (the identity conditions match and a
situational condition fails), opens a `tacit.escalation` task and adds a required human action.
A `tacit.retrieval_decision` artefact and an evidence entry are produced for every recorded
attempt.

## 7. Memory-object rules

A `tacit.memory_object` is created only from a promoted, active, consenting fragment. Evidence-layer
fragments must never become agent-visible memory. Advisory fragments become advisory context;
controlled fragments become controlled instruction only with change-control metadata. Memory
objects always carry use constraints.

## 8. Model-assist rules

Every local-model contribution is recorded as a `tacit.model_assist_record`, for provenance. Model
output cannot promote, reject, revoke, authorise, or retrieve a fragment; it remains a draft for
human review, and `human_review_required` defaults to true.

## 9. Consent rules

Promotion beyond Evidence requires valid consent or an explicitly recorded policy exception. The
worker states consent with their answer to a whisper; a declined answer records a
`consent_declined` validation event and stores nothing. Withdrawn consent blocks future retrieval,
and only the worker who contributed a fragment can withdraw it. Workers can see records tied to
their contribution and can challenge, correct, propose a supersession, or request re-elicitation
through auditable events.
