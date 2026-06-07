# Example 2: Batch quality visual inspection

**Categories:** `K8_aesthetic`, `K7_sensory`

## Scenario

A quality specialist flags a resin batch as "looks off" before the lab measure confirms drift.
This is perceptual and aesthetic tacit knowledge. It is real and valuable, and it is dangerous to
turn into a universal rule, so the evidence stays weak and the fragment stays advisory.

## Run it

```bash
tacitflow demo batch-quality-visual-inspection
```

This runs the full Observe, Infer, Whisper, Confirm, Remember loop, promotes the fragment to the
Advisory layer through a Mission Group review, builds a governed tacit memory object, and shows
retrieval allowed under the matching context and blocked under the non-matching one.

## What it demonstrates

The fragment is promoted only as advisory context, never as automation. Its use constraints require
exemplar comparison and a human confirmation before any action: "do not convert into a universal
rule" and "ask a human to confirm against annotated exemplars before action". Because the evidence
is weak (two cases, with a counterexample on record), both the Mission Group and the retrieval gate
keep it firmly advisory.

## Files

The folder mirrors Example 1: `observation.json`, `context_matching.json`,
`context_non_matching.json`, `procedural_memory/`, `semantic_memory/`, `episodic_memory/`,
`fragment_evidence.json`, `mission_group_review.json`, `whisper_response.json`,
`tacit_memory/expected_tacit_memory_object.json`, `expected_agent_context.json`, and
`expected_audit.jsonl`.

```bash
tacitflow retrieve --context examples/batch_quality_visual_inspection/context_matching.json
tacitflow memory query --context examples/batch_quality_visual_inspection/context_matching.json
```
