# Memory architecture

Metis models four memory stores and shows how an AI agent uses them together.

**Procedural memory** holds what is formally prescribed: SOPs, workflows, checklists, policies.
**Semantic memory** holds general organisational knowledge: concepts, facts, equipment and product
metadata. **Episodic memory** holds specific past events: incidents, prior cases, agent runs, and
CHAP evidence events. **Tacit memory**, the fourth stratum, holds validated fragments of situated
human practice, each carrying provenance, conditions, authority, validation state, consent, review
status, and retrieval constraints.

Metis primarily builds this fourth stratum. The first three are represented by simple stores
(`memory/procedural.py`, `semantic.py`, `episodic.py`) that the broker queries directly: formal
procedures, general facts, and past cases are already sanctioned for use, while situated guidance
has to pass the gate each time.

## TacitMemoryObject

A `TacitMemoryObject` (`memory/tacit.py`) is a promoted, governed, memory-ready representation of a
`TacitFragment`. It is created only when a fragment has passed Tier-2 and is active and consenting.
It records `agent_visibility` (`hidden`, `retrievable_with_gate`, `advisory_context`, or
`controlled_instruction`), a retrieval policy, use constraints, a review date, and links back to
procedural, semantic, and episodic refs and to CHAP evidence entries. Evidence-layer fragments stay
out of agent-visible memory; advisory fragments become advisory context; controlled fragments become
controlled instruction only with change-control metadata.

## AgentMemoryContext

An `AgentMemoryContext` (`memory/agent_context.py`) is what an agent receives at runtime. It keeps
the four memory types distinct so the agent can tell what is formally prescribed (procedural), what
is general knowledge (semantic), what has happened before (episodic), and what is validated situated
guidance under constraints (tacit). It also carries blocked tacit results with reasons, governance
notes, required human actions, the id of any escalation task, citations, and audit references.

## MemoryBroker

The `MemoryBroker` (`memory/broker.py`) receives a runtime task context, queries procedural,
semantic, and episodic memory, and queries tacit memory **only through the retrieval gate**. Blocked
tacit results go to the audit trail with their reasons and stay out of the guidance. When a blocked
result needs a person (a high-risk situation or a near miss), the broker adds the required human
action and, for a recorded query, opens a `tacit.escalation` task. A recorded query also emits
`tacit.retrieval_decision` and `tacit.agent_memory_context` artefacts to the CHAP evidence chain.

## How agents should use tacit memory

An agent uses tacit memory as situated guidance for its recorded conditions. It respects the use
constraints, presents advisory cues to a person for confirmation, hands decisions to a person when
the context lists required human actions, and cites provenance and audit references. See
[agent_memory_use.md](agent_memory_use.md).
