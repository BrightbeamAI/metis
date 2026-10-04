# The `metis/1.0` profile

`metis/1.0` is a CHAP profile. It extends CHAP through declared task kinds, artefact kinds,
metadata conventions, and validation rules, leaves CHAP Core unchanged, and uses CHAP's own
envelope and wire methods. The authoritative profile document is
[../profiles/metis.md](../profiles/metis.md).

## Task kinds

The reference implementation opens `tacit.capture` (a capture, on which the fragment's first
Tier-2 review also runs), `tacit.validate.tier2` (a fresh review of a held fragment or of a
fragment in use), `tacit.re_elicit` (a re-elicitation decided at Tier-2), `tacit.retrieve`, and
`tacit.escalation` tasks, and records every artefact
except the whisper prompt as a completed task of the artefact's kind (`tacit.control` records a
control event). The profile also declares
`tacit.infer`, `tacit.whisper`, `tacit.confirm`, `tacit.validate.tier1`, `tacit.promote`,
`tacit.reject`, `tacit.hold`, `tacit.memory.prepare`, `tacit.memory.query`, `tacit.model.assist`,
`tacit.revoke`, `tacit.supersede`, and `tacit.export_audit` for implementations that model those
steps as separate tasks.

## Artefact kinds

`tacit.fragment`, `tacit.memory_object`, `tacit.agent_memory_context`, `tacit.capture_observation`,
`tacit.inference_candidate`, `tacit.whisper_prompt`, `tacit.whisper_response`,
`tacit.operator_confirmation`, `tacit.validation_event`, `tacit.review_decision`,
`tacit.promotion_record`, `tacit.rejection_record`, `tacit.re_elicitation_request`,
`tacit.retrieval_decision`, `tacit.revocation_record`, `tacit.supersession_record`,
`tacit.consent_record`, `tacit.model_assist_record`, `tacit.membership_record`. Each carries a `schema` reference, as CHAP
requires for implementation-defined kinds; JSON Schemas for the core kinds live in
[../schemas/](../schemas/), one file per kind.

## Validation states

`captured`, `worker_confirmed`, `tier1_confirmed`, `tier2_pending`, `promoted_to_advisory`,
`promoted_to_controlled`, `held`, `rejected`, `re_elicit`, plus lifecycle states `withdrawn`,
`superseded`, `expired`.

## Authority layers, review, retrieval, memory, model-assist, consent

See [governance_model.md](governance_model.md), [condition_aware_retrieval.md](condition_aware_retrieval.md),
[memory_architecture.md](memory_architecture.md), and [local_model_runtime.md](local_model_runtime.md).
In short: Evidence/Advisory/Controlled gate what a fragment may do; promotion needs a quorum of
named Mission Group reviewers (`quorum:2` by default); retrieval is condition-aware and
deterministic, and hands high-risk situations and near misses to a person through a
`tacit.escalation` task; memory objects come only from promoted fragments and always carry use
constraints; model assistance is recorded for provenance and stays advisory; and promotion beyond
Evidence requires valid consent or a recorded policy exception.
