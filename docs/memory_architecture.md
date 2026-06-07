# Memory architecture

TacitFlow models four memory stores and shows how an AI agent uses them together.

**Procedural memory** holds what is formally prescribed: SOPs, workflows, checklists, policies.
**Semantic memory** holds general organisational knowledge: concepts, facts, equipment and product
metadata. **Episodic memory** holds specific past events: incidents, prior cases, agent runs, and
CHAP evidence events. **Tacit memory**, the fourth stratum, holds validated fragments of situated
human practice, each carrying provenance, conditions, authority, validation state, consent, review
status, and retrieval constraints.

TacitFlow primarily builds the fourth store. The first three are represented by simple stores
(`memory/procedural.py`, `semantic.py`, `episodic.py`) that the broker queries directly, because
formal procedures, general facts, and past cases are not access-controlled in the way situated
guidance must be.

## TacitMemoryObject

A `TacitMemoryObject` (`memory/tacit.py`) is a promoted, governed, memory-ready representation of a
`TacitFragment`. It is created only when a fragment has passed Tier-2 and is active and consenting.
It records `agent_visibility` (`hidden`, `retrievable_with_gate`, `advisory_context`, or
`controlled_instruction`), a retrieval policy, use constraints, and links back to procedural,
semantic, and episodic refs and to CHAP evidence entries. Evidence-layer fragments can never become
an agent-visible memory object; advisory fragments become advisory context; controlled fragments
become controlled instruction only with change-control metadata.

## AgentMemoryContext

An `AgentMemoryContext` (`memory/agent_context.py`) is what an agent receives at runtime. It keeps
the four memory types distinct so the agent can tell what is formally prescribed (procedural), what
is general knowledge (semantic), what has happened before (episodic), and what is validated situated
guidance under constraints (tacit). It also carries blocked tacit results with reasons,
governance notes, required human actions, citations, and audit references.

## MemoryBroker

The `MemoryBroker` (`memory/broker.py`) receives a runtime task context, queries procedural,
semantic, and episodic memory, and queries tacit memory **only through the retrieval gate**. Blocked
tacit results are recorded in the audit trail but never exposed as usable guidance. The broker can
optionally emit `tacit.retrieval_decision` and `tacit.agent_memory_context` artefacts to the CHAP
evidence chain.

## How agents should use tacit memory

As situated guidance, not as ground truth. The agent must respect the use constraints, present
advisory cues for human confirmation rather than acting automatically, escalate where required, and
cite provenance and audit references. See [agent_memory_use.md](agent_memory_use.md).
