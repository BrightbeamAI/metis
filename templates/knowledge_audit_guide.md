# Knowledge Audit Guide (Discovery: breadth)

The Knowledge Audit maps the range of expertise in a role before any detailed capture. It is
broad and shallow: it finds where tacit knowledge matters, so in-flow whispers and focused
interviews can be aimed. Run it at Discovery, when a workflow is first brought into Metis or
after a major change to equipment, products, or teams. Interview one experienced practitioner
at a time, with their consent, away from live work.

For each probe, ask for a concrete example, then ask what a less experienced colleague would
miss. Record the practitioner's own words.

| Probe | Ask | Points to |
|-------|-----|-----------|
| Past and future | "Is there a time you saw a problem coming before anyone else did?" | K11 anticipatory |
| Big picture | "What do you keep in your head about the whole line that a newcomer would not?" | K14 collaborative, K17 strategic |
| Noticing | "What do you see, hear, or feel that tells you something is off?" | K7 sensory, K8 aesthetic |
| Job smarts | "What shortcuts or habits make you faster or safer than the procedure alone?" | K9 heuristic, K3 rhythmic |
| Improvising | "When did the standard way fail you, and what did you do then?" | K9 heuristic, K10 diagnostic |
| Self-monitoring | "How do you know when you are out of your depth, and what do you do then?" | K12 metacognitive |
| Anomalies | "What tells you a reading or result cannot be trusted?" | K10 diagnostic |
| Equipment | "Which machine or tool behaves differently from its manual, and how do you handle it?" | K4 equipment-specific, K6 tool-extended |

## From audit to Metis

Each example that names a cue, a response, and the situation becomes one observation. Enter it
with the practitioner present, so their confirmation is the Tier-1 check:

```python
from metis.conditions.context import TacitContext

eng.capture_observation(
    {
        "observation_id": "KA-07",
        "work_as_imagined": "Run pump A at the set load until the alarm.",
        "work_as_done": "Ease back when the note dulls under high load.",
        "context": TacitContext(equipment_id="PUMP-A", operating_mode="high_load"),
        "source": "interview:knowledge_audit",
    },
    consent=consent,            # the practitioner's recorded consent
    response="confirm",         # the practitioner confirms the wording in the interview
    category="K7_sensory",
)
```

The fragment lands in the Evidence layer like any other and waits for Mission Group review.
Examples that are too thin to state a cue and a situation become topics for a Critical Decision
Method interview (`cdm_interview_guide.md`) or for in-flow whispers.
