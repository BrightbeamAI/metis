# Example 2: Batch quality visual inspection

**Categories:** `K8_aesthetic`, `K7_sensory`

## Scenario

A quality specialist flags a resin batch as "looks off" before the lab measure confirms drift.
This is perceptual and aesthetic tacit knowledge: real, valuable, and risky to generalise. With two
cases and a counterexample on record, the evidence is weak, so the fragment stays advisory.

## Run it

```bash
metis demo batch-quality-visual-inspection
```

This runs the full Observe, Infer, Whisper, Confirm, Store loop, promotes the fragment to the
Advisory layer through a quorum of Mission Group reviewers, builds a governed tacit memory object,
and shows retrieval allowed under the matching context and blocked under the non-matching one.

## What it demonstrates

The fragment is promoted as advisory context for a person to act on. Its use constraints require
exemplar comparison and a human confirmation before any action: "do not convert into a universal
rule" and "ask a human to confirm against annotated exemplars before action". Because the evidence
is weak (two cases, with a counterexample on record), its evidence-derived confidence is low and the
Mission Group promotes it to Advisory only.

## Files

The folder mirrors Example 1: `observation.json`, `context_matching.json`,
`context_non_matching.json`, `procedural_memory/`, `semantic_memory/`, `episodic_memory/`,
`fragment_evidence.json`, `mission_group_review.json`, `whisper_response.json`,
`tacit_memory/expected_tacit_memory_object.json`, `expected_agent_context.json`, and
`expected_audit.jsonl`.

```bash
metis retrieve --context examples/batch_quality_visual_inspection/context_matching.json
metis memory query --context examples/batch_quality_visual_inspection/context_matching.json
```
