# The `tacitflow/1.0` profile

`tacitflow/1.0` is a CHAP profile. It extends CHAP through declared task kinds, artefact kinds,
metadata conventions, and validation rules. It does **not** modify CHAP Core, and it introduces no
new envelope or wire methods. The authoritative profile document is [../profiles/tacitflow.md](../profiles/tacitflow.md).

## Task kinds

`tacit.capture`, `tacit.infer`, `tacit.confirm`, `tacit.validate.tier1`, `tacit.validate.tier2`,
`tacit.promote`, `tacit.reject`, `tacit.hold`, `tacit.re_elicit`, `tacit.retrieve`,
`tacit.memory.prepare`, `tacit.memory.query`, `tacit.model.assist`, `tacit.revoke`,
`tacit.supersede`, `tacit.export_audit`.

## Artefact kinds

`tacit.fragment`, `tacit.memory_object`, `tacit.agent_memory_context`, `tacit.capture_observation`,
`tacit.inference_candidate`, `tacit.whisper_prompt`, `tacit.whisper_response`,
`tacit.operator_confirmation`, `tacit.validation_event`, `tacit.review_decision`,
`tacit.promotion_record`, `tacit.rejection_record`, `tacit.re_elicitation_request`,
`tacit.retrieval_decision`, `tacit.revocation_record`, `tacit.supersession_record`,
`tacit.consent_record`, `tacit.model_assist_record`. Each carries a `schema` reference, as CHAP
requires for implementation-defined kinds; the JSON Schemas live in [../schemas/](../schemas/).

## Validation states

`captured`, `worker_confirmed`, `tier1_confirmed`, `tier2_pending`, `promoted_to_advisory`,
`promoted_to_controlled`, `held`, `rejected`, `re_elicit`, plus lifecycle states `withdrawn`,
`superseded`, `expired`.

## Authority layers, retrieval, memory, model-assist, consent

See [governance_model.md](governance_model.md), [condition_aware_retrieval.md](condition_aware_retrieval.md),
[memory_architecture.md](memory_architecture.md), and [local_model_runtime.md](local_model_runtime.md).
In short: Evidence/Advisory/Controlled gate what a fragment may do; retrieval is condition-aware and
deterministic; memory objects come only from promoted fragments and always carry use constraints;
model assistance is provenance, never authority; and promotion beyond Evidence requires valid consent
or a recorded policy exception.
