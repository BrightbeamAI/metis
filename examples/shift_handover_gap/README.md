# Example 3: Shift handover gap

**Categories:** `K14_collaborative`, `K12_metacognitive`

## Scenario

A team lead senses a handover is incomplete even though the form is filled in. The felt sense of
"something unfinished" is collaborative and meta-cognitive tacit knowledge.

## Run it

```bash
tacitflow demo shift-handover-gap
```

This runs the full capture loop, promotes the fragment to the Advisory layer, builds a governed
tacit memory object, and shows the retrieval gate allowing it under the matching handover context
and blocking it elsewhere.

## What it demonstrates

The promoted memory is presented as a handover checklist prompt, not automation. Its use constraints
require a verbal confirmation from the incoming lead and forbid auto-closing the handover: "ask the
incoming lead to confirm open threads verbally" and "do not auto-close the handover". This is how a
collaboration cue becomes governed guidance that supports a human rather than replacing one.

## Files

The folder mirrors Example 1: `observation.json`, `context_matching.json`,
`context_non_matching.json`, `procedural_memory/`, `semantic_memory/`, `episodic_memory/`,
`fragment_evidence.json`, `mission_group_review.json`, `whisper_response.json`,
`tacit_memory/expected_tacit_memory_object.json`, `expected_agent_context.json`, and
`expected_audit.jsonl`.

```bash
tacitflow retrieve --context examples/shift_handover_gap/context_matching.json
tacitflow memory query --context examples/shift_handover_gap/context_matching.json
```
