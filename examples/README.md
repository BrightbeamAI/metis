# Examples

Three small, fully local, synthetic examples. Each runs end to end with deterministic fixtures
(no cloud APIs, no live model needed) and produces a replayable CHAP evidence chain.

| Example | Categories | What it shows |
|---------|-----------|----------------|
| [manufacturing_pump_vibration](manufacturing_pump_vibration/) | K7 sensory, K10 diagnostic, K4 equipment | A sensory cue ("dull acoustic" + low-frequency vibration) becomes an advisory cue, retrievable only under the matching pump and operating mode. |
| [batch_quality_visual_inspection](batch_quality_visual_inspection/) | K8 aesthetic, K7 sensory | A "looks off" judgement stays advisory with weak evidence and an exemplar-confirmation constraint, never a universal rule. |
| [shift_handover_gap](shift_handover_gap/) | K14 collaborative, K12 meta-cognitive | A felt-incomplete handover becomes a checklist prompt that asks a human to confirm, never auto-closes. |

## Run any example

```bash
tacitflow demo manufacturing-pump-vibration
tacitflow demo batch-quality-visual-inspection
tacitflow demo shift-handover-gap
```

Then inspect the gate directly with the example contexts:

```bash
tacitflow retrieve --context examples/manufacturing_pump_vibration/context_matching.json
tacitflow retrieve --context examples/manufacturing_pump_vibration/context_non_matching.json
tacitflow memory query --context examples/manufacturing_pump_vibration/context_matching.json
```

## What is in each folder

Every example carries the same files: `observation.json` (the situated observation),
`context_matching.json` and `context_non_matching.json` (runtime contexts for the gate),
`procedural_memory/`, `semantic_memory/`, `episodic_memory/` (the other three memory stores),
`fragment_evidence.json`, `mission_group_review.json`, `whisper_response.json` (the capture and
review record), and the expected outputs: `tacit_memory/expected_tacit_memory_object.json`,
`expected_agent_context.json`, and `expected_audit.jsonl`.

These expected files are generated from the implementation by `scripts/generate_examples.py`, so
they always match what the code produces.
