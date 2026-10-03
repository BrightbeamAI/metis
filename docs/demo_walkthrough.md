# Demo walkthrough

```bash
metis init
metis demo manufacturing-pump-vibration
```

The manufacturing pump-vibration demo runs the whole pipeline on your machine and prints each step
with a label:

1. Metis workspace created.
2. Participants added (operator, whisperer agent, the Mission Group and its three named reviewers,
   assistant agent).
3. Procedural memory loaded (SOP-17).
4. Semantic memory loaded (equipment + vibration concepts).
5. Episodic memory loaded (prior cases).
6. Local model status checked (deterministic fixtures, or a live Gemma model with `--live-model`).
7. Observation loaded (work-as-imagined vs work-as-done gap).
8. Candidate fragment inferred (a hypothesis for the worker to confirm).
9. Local AI assistance recorded (model-assist records, from fixtures or the live model).
10. Whisper generated (CHAP whisper capability).
11. Operator confirmation recorded (Tier-1).
12. Evidence-layer fragment stored.
13. Mission Group review recorded (Tier-2): two named reviewers approve under `quorum:2`.
14. Fragment promoted to the Advisory layer, with a review date.
15. Tacit memory object created.
16. Retrieval allowed under the matching context.
17. Retrieval blocked under the non-matching context.
18. Agent memory context generated (procedural + semantic + episodic + tacit).
19. Audit chain ready for export.

Then explore the result:

```bash
metis fragment list
metis fragment show TF-00001
metis memory list
metis memory show TM-00001
metis retrieve --context examples/manufacturing_pump_vibration/context_matching.json
metis retrieve --context examples/manufacturing_pump_vibration/context_non_matching.json
metis memory query --context examples/manufacturing_pump_vibration/context_matching.json
metis audit read
metis audit verify
metis audit export --out evidence.jsonl
```

Under the matching context the advisory fragment is eligible and presented with its use constraints;
under the non-matching context it is blocked with `conditions_do_not_match`. The agent memory context
combines all four memory stores and lists the required human actions. Each `retrieve` and
`memory query` is itself recorded: the workspace's chain grows, and `metis audit verify` confirms
that the CHAP store and the append-only ledger agree entry for entry. The exported `evidence.jsonl`
is the full CHAP evidence chain, independently replayable and verifiable.

Try a high-risk context (set `"risk_class": "high"`): the fragment is withheld, an escalation task
is opened for the operator, and the output names the required human action.

The other two examples run the same way:

```bash
metis demo batch-quality-visual-inspection
metis demo shift-handover-gap
```

`metis capture --example <scenario>` runs the same capture into a new workspace with less output.
