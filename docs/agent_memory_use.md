# How an AI agent should use Metis output

Metis gives an agent an `AgentMemoryContext`. Using it correctly is part of the governance.

**Tacit memory is not ground truth.** It is a validated, situated trace of human practice, not a
fact. **It is not an SOP**, procedural memory is where formal rules live. **It is not a training
example.** It is governed, situated guidance.

An agent consuming Metis output must:

- **Respect the use constraints** attached to every tacit entry. If the constraint says "present as
  an advisory cue only" or "do not automatically reduce throughput", the agent must not act
  automatically.
- **Treat advisory memory as a cue for a human**, not as a decision. Where a constraint says "ask the
  human operator to confirm", surface the cue and wait.
- **Escalate where required.** If the situation's risk class requires human escalation, the gate will
  not return the fragment; the agent must escalate rather than improvise.
- **Cite provenance and audit references.** Each tacit entry carries citations and audit refs so the
  agent's action can be reconstructed later.
- **Never promote or author its own operational knowledge.** Anything an agent surfaces from its own
  traces is an endogenous fragment in the Evidence layer and must pass Mission Group review.

Local model assistance must never override these constraints. A model may rephrase advisory wording
from an already-validated, gate-eligible memory object, but it cannot change the retrieval result,
the constraints, or the eligibility.
