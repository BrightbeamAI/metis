# Demo walkthrough

```bash
tacitflow init
tacitflow demo manufacturing-pump-vibration
```

The manufacturing pump-vibration demo runs the whole pipeline locally, no cloud APIs, and prints
nineteen labelled steps:

1. TacitFlow workspace created.
2. Participants added (operator, whisperer agent, Mission Group, assistant agent).
3. Procedural memory loaded (SOP-17).
4. Semantic memory loaded (equipment + vibration concepts).
5. Episodic memory loaded (prior cases).
6. Local model status checked (live Gemma if available, else deterministic fixtures).
7. Observation loaded (work-as-imagined vs work-as-done gap).
8. Candidate fragment inferred (a hypothesis only).
9. Local AI assistance recorded (model-assist records; live Gemma or fixtures).
10. Whisper generated (CHAP whisper capability).
11. Operator confirmation recorded (Tier-1).
12. Evidence-layer fragment stored.
13. Mission Group review recorded (Tier-2).
14. Fragment promoted to the Advisory layer.
15. Tacit memory object created.
16. Retrieval allowed under the matching context.
17. Retrieval blocked under the non-matching context.
18. Agent memory context generated (procedural + semantic + episodic + tacit).
19. Audit chain ready for export.

Then explore the result:

```bash
tacitflow fragment list
tacitflow fragment show TF-00001
tacitflow memory list
tacitflow memory show TM-00001
tacitflow retrieve --context examples/manufacturing_pump_vibration/context_matching.json
tacitflow retrieve --context examples/manufacturing_pump_vibration/context_non_matching.json
tacitflow memory query --context examples/manufacturing_pump_vibration/context_matching.json
tacitflow audit read
tacitflow audit export --out evidence.jsonl
```

Under the matching context the advisory fragment is eligible and presented with its use constraints;
under the non-matching context it is blocked with `conditions_do_not_match`. The agent memory context
combines all four memory stores and lists the required human actions. The exported `evidence.jsonl`
is the full CHAP evidence chain, independently replayable and verifiable.

The other two examples run the same way:

```bash
tacitflow capture --example batch-quality-visual-inspection
tacitflow capture --example shift-handover-gap
```
