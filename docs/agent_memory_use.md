# How an AI agent should use Metis output

Metis gives an agent an `AgentMemoryContext`. Using it correctly is part of the governance.

The context keeps four kinds of memory apart. Procedural memory holds the formal rules, semantic
memory holds facts, and episodic memory holds past cases. **Tacit memory holds governed, situated
guidance**: a validated trace of human practice that applies under its recorded conditions and
stays open to challenge.

An agent consuming Metis output must:

- **Respect the use constraints** attached to every tacit entry. If the constraint says "present as
  an advisory cue only" or "do not automatically reduce throughput", the agent must not act
  automatically.
- **Treat advisory memory as a cue for a person.** Where a constraint says "ask the human operator
  to confirm", surface the cue and wait for that confirmation.
- **Stop when a person must decide.** In a high-risk situation, or when a fragment matches the
  equipment and the situation differs (a near miss), the gate withholds the guidance. Metis opens
  an escalation task for the operator and puts a required human action in the agent's context. The
  agent hands the decision to that person and waits.
- **Cite provenance and audit references.** Each tacit entry carries citations and audit refs so the
  agent's action can be reconstructed later.
- **Never promote or author its own operational knowledge.** Anything an agent surfaces from its own
  traces is an endogenous fragment in the Evidence layer and must pass Mission Group review.

Agents connected through the [MCP server](mcp_server.md) get the same contract: guidance only
through the gate, required human actions alongside it, and no tool that grants authority.

Local model assistance must never override these constraints. A model may rephrase advisory wording
from an already-validated, gate-eligible memory object, but it cannot change the retrieval result,
the constraints, or the eligibility.
