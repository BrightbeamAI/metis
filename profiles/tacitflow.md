# Profile: `tacitflow`

**Profile id:** `tacitflow/1.0` · **Depends on:** CHAP Core, `review/1.0`, `whisper/1.0`, `routing/1.0`, `control/1.0`, `handoff/1.0`

The `tacitflow/1.0` profile defines TacitFlow-specific **task kinds**, **artefact kinds**,
metadata conventions, validation states, authority layers, consent rules, revocation rules,
memory-object rules, model-assist rules, and retrieval rules for governed tacit fragment
capture.

This profile **does not modify CHAP Core**. It extends CHAP only through declared artefact
kinds, task kinds, metadata conventions, and validation rules. TacitFlow introduces no new
envelope, no new wire methods, and no parallel evidence mechanism. Every TacitFlow action is
carried by an existing CHAP method (`capture.append`, `whisper.ask`/`whisper.answer`,
`review.request`/`decide.*`, `task.route`, `control.*`, `handoff.*`, `task.create`/`task.update`,
`audit.*`) and recorded in the standard CHAP evidence chain.

---

## 1. Task kinds

```
tacit.capture          tacit.infer            tacit.confirm
tacit.validate.tier1   tacit.validate.tier2   tacit.promote
tacit.reject           tacit.hold             tacit.re_elicit
tacit.retrieve         tacit.memory.prepare   tacit.memory.query
tacit.model.assist     tacit.revoke           tacit.supersede
tacit.export_audit
```

## 2. Artefact kinds

Each non-standard kind carries a `schema` reference (`https://tacitflow.dev/schemas/0.1/<kind>.schema.json`),
exactly as CHAP requires for implementation-defined artefact kinds.

```
tacit.fragment              tacit.memory_object         tacit.agent_memory_context
tacit.capture_observation   tacit.inference_candidate   tacit.whisper_prompt
tacit.whisper_response      tacit.operator_confirmation tacit.validation_event
tacit.review_decision       tacit.promotion_record      tacit.rejection_record
tacit.re_elicitation_request tacit.retrieval_decision   tacit.revocation_record
tacit.supersession_record   tacit.consent_record        tacit.model_assist_record
```

## 3. Validation states

`captured → worker_confirmed → tier1_confirmed → tier2_pending →`
`{ promoted_to_advisory | promoted_to_controlled | held | rejected | re_elicit }`,
with terminal/lifecycle states `withdrawn`, `superseded`, `expired`.

## 4. Authority layers

`evidence` (learning/review only; never operational; never agent-visible) ·
`advisory` (conditional decision support under matching conditions; agent-visible as context) ·
`controlled` (formally incorporated; change-control metadata + exact matching required).

## 5. Retrieval rules

Tacit memory is retrieved only through the condition-aware gate. Eligibility requires that
authority layer, validation state, consent, revocation status, review/expiry, conditions,
exclusions, risk class, role, source pathway, and (for controlled) exact-match constraints all
pass. A `tacit.retrieval_decision` artefact and an evidence entry are produced for every attempt.
Retrieval is never semantic similarity alone, and a local model never decides eligibility.

## 6. Memory-object rules

A `tacit.memory_object` is created only from a promoted, active, consenting fragment. Evidence-layer
fragments must never become agent-visible memory. Advisory fragments become advisory context;
controlled fragments become controlled instruction only with change-control metadata. Memory
objects always carry use constraints.

## 7. Model-assist rules

Every local-model contribution is recorded as a `tacit.model_assist_record` (provenance, not
authority). Model output cannot promote, reject, revoke, authorise, or retrieve a fragment, and
is never treated as ground truth. `human_review_required` defaults to true.

## 8. Consent rules

Promotion beyond Evidence requires valid consent or an explicitly recorded policy exception.
Withdrawn consent blocks future retrieval. Workers can see records tied to their contribution and
can contest, correct, withdraw, supersede, or request re-elicitation through auditable events.
