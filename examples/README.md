# Examples

Three small, fully local, synthetic examples. Each runs end to end on your machine with
deterministic fixtures, so it needs no model server, and produces a replayable CHAP evidence chain.

| Example | Categories | What it shows |
|---------|-----------|----------------|
| [manufacturing_pump_vibration](manufacturing_pump_vibration/) | K7 sensory, K10 diagnostic, K4 equipment-specific | A sensory cue ("dull acoustic" + low-frequency vibration) becomes an advisory cue, retrievable only under its recorded conditions: pump A at high load, on the night shift, before the alarm. |
| [batch_quality_visual_inspection](batch_quality_visual_inspection/) | K8 aesthetic, K7 sensory | A "looks off" judgement stays advisory, with weak evidence and a constraint to confirm against annotated exemplars before any action. |
| [shift_handover_gap](shift_handover_gap/) | K14 collaborative, K12 metacognitive | A felt-incomplete handover becomes a checklist prompt that asks the incoming lead to confirm open threads; a person closes the handover. |

## Run an example

Run one example, then inspect the gate with its own contexts:

```bash
metis demo manufacturing-pump-vibration
metis retrieve --context examples/manufacturing_pump_vibration/context_matching.json
metis retrieve --context examples/manufacturing_pump_vibration/context_non_matching.json
metis memory query --context examples/manufacturing_pump_vibration/context_matching.json
```

The other two run the same way with their own folders: `metis demo batch-quality-visual-inspection`
and `metis demo shift-handover-gap`. Commands act on the active workspace, which is the last demo
you ran; `metis workspace list` shows them all and `metis workspace use <id>` switches.

## What is in each folder

Every example carries the same files: `observation.json` (the situated observation),
`context_matching.json` and `context_non_matching.json` (runtime contexts for the gate),
`procedural_memory/`, `semantic_memory/`, `episodic_memory/` (the other three memory stores),
`fragment_evidence.json`, `mission_group_review.json`, `whisper_response.json` (the capture and
review record, including the named reviewers who approved the promotion), and the expected outputs:
`tacit_memory/expected_tacit_memory_object.json`, `expected_agent_context.json`, and
`expected_audit.jsonl`.

The review records and expected files are generated from the implementation by
`scripts/generate_examples.py`, so they always match what the code produces.
