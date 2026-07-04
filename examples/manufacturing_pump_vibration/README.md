# Example 1, Manufacturing pump vibration

**Categories:** `K7_sensory`, `K10_diagnostic`, `K4_equipment_specific`

## Scenario

SOP-17 (the *work-as-imagined*) says the operator should reduce load **only when the alarm
threshold is crossed**. Experienced operators (the *work-as-done*) reduce throughput **earlier**
when high-load operation coincides with low-frequency vibration and a specific dull acoustic cue.
That gap is a diagnostic signal, a good place to ask a bounded question.

## Run it

```bash
metis demo manufacturing-pump-vibration
```

This runs the full loop locally with deterministic fixtures (or a live Gemma model via
`--live-model` if Ollama is running) and demonstrates, in order:

1. workspace creation and participants (operator, whisperer agent, Mission Group, assistant agent)
2. procedural / semantic / episodic memory loaded
3. local model status check
4. observation → inference candidate (hypothesis only) → optional model-assisted structuring
5. a CHAP whisper and the operator confirmation
6. an Evidence-layer `tacit.fragment`
7. Mission Group Tier-2 review → promotion to Advisory
8. a `tacit.memory_object`
9. retrieval **allowed** under the matching context, **blocked** under the non-matching context
10. an `AgentMemoryContext` combining procedural, semantic, episodic, and tacit memory
11. an exported, replayable CHAP evidence chain

## Files

| File | Role |
|------|------|
| `observation.json` | the situated observation (work-as-imagined vs work-as-done) |
| `work_as_done_log.csv` | synthetic in-flow log showing the cue/action pattern |
| `procedural_memory/formal_procedure.md` | SOP-17 (work-as-imagined baseline) |
| `semantic_memory/*.json` | equipment + vibration concepts |
| `episodic_memory/prior_cases.jsonl` | prior cases (incl. CHAP-style outcomes) |
| `whisper_response.json` | the operator's Tier-1 confirmation |
| `fragment_evidence.json` | the evidence summary the Mission Group weighs |
| `mission_group_review.json` | the Tier-2 decision |
| `context_matching.json` / `context_non_matching.json` | runtime contexts for the gate |
| `tacit_memory/expected_tacit_memory_object.json` | the promoted, governed memory object |
| `expected_agent_context.json` | the agent-facing context under the matching situation |
| `expected_audit.jsonl` | the full replayable CHAP evidence chain |

## Try the gate directly

```bash
metis retrieve --context examples/manufacturing_pump_vibration/context_matching.json
metis retrieve --context examples/manufacturing_pump_vibration/context_non_matching.json
metis memory query --context examples/manufacturing_pump_vibration/context_matching.json
```

The advisory memory is presented with use constraints, "present as an advisory cue only", "do
not automatically reduce throughput", "ask the human operator to confirm the acoustic cue",
"escalate if risk class is high", never as an automatic action.
