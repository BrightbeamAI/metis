# Metis documentation

Start with the visual explainer or the interactive demo, then dig into the concept and reference docs.

- **[demo.html](demo.html)** is an interactive demo. Pick a scenario, step through the capture loop,
  and drive the retrieval gate yourself by editing the runtime context and watching it allow or block.
- **[explainer.html](explainer.html)** is a single-page, illustrated tour of Metis with
  diagrams and the three demo walkthroughs. Open it in a browser.

## Start here

| Doc | What it covers |
|-----|----------------|
| [architecture.md](architecture.md) | The four layers, the capture loop, validation, the retrieval gate, the memory broker, and the audit flow. |
| [demo_walkthrough.md](demo_walkthrough.md) | The 19 steps the manufacturing demo prints, plus the commands to inspect the result. |

## Concepts

| Doc | What it covers |
|-----|----------------|
| [memory_architecture.md](memory_architecture.md) | Procedural, semantic, episodic, and tacit memory; the TacitMemoryObject, AgentMemoryContext, and MemoryBroker. |
| [governance_model.md](governance_model.md) | Capture Cell, Mission Group, Runtime Orchestrator, the three authority layers, Tier-1 and Tier-2 review, and lifecycle transitions. |
| [condition_aware_retrieval.md](condition_aware_retrieval.md) | Why retrieval is a governance gate, the ordered checks, and the closed set of blocked reasons. |
| [taxonomy_k1_k17.md](taxonomy_k1_k17.md) | The K1 to K17 tacit categories, the six domains, and the source pathways. |
| [agent_memory_use.md](agent_memory_use.md) | How an AI agent should consume Metis output and respect use constraints. |

## Reference

| Doc | What it covers |
|-----|----------------|
| [chap_integration.md](chap_integration.md) | How Metis maps onto CHAP and which CHAP capabilities it uses. |
| [metis_profile.md](metis_profile.md) | The `metis/1.0` profile: task kinds, artefact kinds, and rules. |
| [local_model_runtime.md](local_model_runtime.md) | Installing Ollama, pulling Gemma, configuration, and why model output stays advisory. |
| [ethical_use.md](ethical_use.md) | The constraints that make capture safe; see also the top-level ETHICAL_USE.md. |

JSON Schemas for every `tacit.*` object are in [../schemas/](../schemas/). The runnable examples
are in [../examples/](../examples/).
