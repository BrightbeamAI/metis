# Critical Decision Method Interview Guide (Discovery: depth)

The Critical Decision Method (CDM) reconstructs one demanding incident in depth: the cues the
practitioner noticed, what those cues meant to them, the options they weighed, and why they
chose as they did. It is narrow and deep. Use it at Discovery for the decisions the Knowledge
Audit flagged, and in full when a mini-CDM (`mini_cdm_interview_guide.md`) shows that a short
walkthrough leaves questions open. Interview after the event, away from live pressure, with
consent.

## Four sweeps

1. **Select the incident.** "Tell me about a time your experience changed the outcome." Choose
   one incident where the practitioner made a judgement the procedure did not spell out.
2. **Build the timeline.** Walk through it start to finish. Mark each decision point and confirm
   the order of events with the practitioner.
3. **Deepen each decision point.**
   - Cues: "What were you seeing, hearing, or feeling at this moment?"
   - Knowledge: "What did you know that told you what that meant?"
   - Goals: "What were you trying to achieve or prevent?"
   - Options: "What else could you have done? Why not that?"
   - Basis: "How did you decide? Was it a rule, a comparison, a feeling?"
   - Experience: "Where did you learn to read it this way?"
   - Aids: "Did any instrument, record, or colleague help?"
4. **Ask what-if questions.** "What if the load had been lower? What would a newcomer have done?
   When would your reasoning have misled you?" These answers set the conditions and exclusions.

## From interview to Metis

Each decision point that yields a cue, a response, and its conditions becomes one observation,
confirmed by the practitioner before you close the interview:

```python
eng.capture_observation(
    {
        "observation_id": "CDM-03",
        "work_as_imagined": "Accept any result inside the specification.",
        "work_as_done": "Re-run the sample when the peak shape is irregular, even in spec.",
        "context": TacitContext(product_family="resin_batch", trigger_context="peak_irregular"),
        "source": "interview:cdm",
    },
    consent=consent,
    response="confirm",
    category="K10_diagnostic",
)
```

Record the what-if answers as `exclusion_conditions` and counterexamples in the fragment's
evidence. They mark the limits beyond which the fragment stops holding.
