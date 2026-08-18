# About Metis

This page is the orientation and reference for the repository. For the pitch, the core concept,
and a runnable example, start with the [README](README.md). For depth on any topic, see the
[documentation index](docs/README.md).

## What Metis is

Metis is a local-first Python toolkit and reference architecture for capturing fragments of
human practice, governing them, and serving the validated ones to AI agents as memory the agent is
allowed to use. It implements the governed tacit-memory layer from the paper *Tacit Fragments: Operationalising
Tacit Knowledge as a Governed Memory Layer for Agentic AI*.

It runs on [CHAP](https://github.com/BrightbeamAI/chap), the Collaborative Human-Agent Protocol, so
every capture, review, retrieval, and revocation is a structured, append-only, hash-linked
collaboration event rather than an ad hoc log.

## The four memory stores

Metis models the four kinds of memory an agent draws on, and keeps them distinct so an agent can
tell a prescribed rule from a general fact from a past case from situated, governed guidance.

| Store | Holds | Access |
|-------|-------|--------|
| Procedural | SOPs, checklists, policies, prescribed sequences | direct |
| Semantic | concepts, facts, equipment and product metadata | direct |
| Episodic | past events, incidents, prior cases | direct |
| Tacit (the fourth store) | validated fragments of situated practice, with conditions, authority, consent, and use constraints | only through the retrieval gate |

Metis primarily builds the fourth store. A `MemoryBroker` assembles an `AgentMemoryContext` that
combines all four, and tacit memory is reached only through a condition-aware gate that travels with
its use constraints.

<p align="center"><img src="docs/assets/memory_stack.svg" alt="The four memory stores and the memory broker" width="100%"></p>

See [docs/memory_architecture.md](docs/memory_architecture.md) for the full model.

## Repository map

| Path | What is there |
|------|----------------|
| `metis/` | the toolkit: `fragment/`, `taxonomy/`, `conditions/`, `consent/`, `capture/`, `validation/`, `governance/`, `retrieval/`, `memory/`, `models/`, `audit/`, `storage/`, `cli/`, `api/`, `integrations/chap/`, plus `engine.py` and `scenarios.py` |
| `examples/` | three runnable synthetic examples with inputs, contexts, and expected outputs ([index](examples/README.md)) |
| `docs/` | concept and reference docs, plus the visual `explainer.html` and interactive `demo.html` ([index](docs/README.md)) |
| `schemas/` | JSON Schemas for every `tacit.*` object |
| `profiles/` | the `metis/1.0` CHAP profile |
| `prompts/` | whisper templates (K2 to K14) and model-assist prompt templates |
| `templates/` | capture canvas, review checklist, consent and revocation records |
| `tests/` | pytest suite, runs without a live model |
| `scripts/` | `acceptance_check.py`, `generate_examples.py`, `build_demo.py` |

## How Metis relates to CHAP

Metis does not define a protocol. It runs on CHAP, which provides workspaces, participants,
tasks, artefacts, whisper and review and control events, and an append-only, hash-linked evidence chain.
Metis depends on the official `chap-coordinator` Python reference implementation. The adapter
(`metis/integrations/chap/`) drives a real Coordinator via JSON-RPC dispatch and reuses its
canonical JCS, id, and hash-linked evidence-chain primitives rather than re-implementing the protocol.
A compliance checker reads the method allow-list straight from the Coordinator, so Metis cannot use
a method the reference does not implement; the `tacit.*`
names are artefact and task kinds declared by the `metis/1.0` profile, which is how CHAP is meant
to be extended.

| Metis concept | CHAP concept |
|-------------------|--------------|
| Capture Cell | workspace with human, agent, service, and group participants |
| Operator, Whisperer, Mission Group | human, agent, group participants |
| Tacit fragment, memory object, agent context | artefacts of kind `tacit.*` with a schema reference |
| Whisper, operator confirmation | `whisper.ask` / `whisper.answer` |
| Mission Group review | `review.request` and `decide.*` |
| Revocation, supersession | `control.*` events plus records |
| Audit trail | Hash-linked (JCS) evidence chain; Ed25519 signing via the security-signed/1.0 profile |

Full detail and the complete mapping are in [docs/chap_integration.md](docs/chap_integration.md), and
the profile is in [profiles/metis.md](profiles/metis.md).

## Local model runtime

Metis assists capture with a local model and never calls a cloud API. It defaults to Ollama and
the Gemma family. The demo and the tests run without any model using deterministic fixtures.

```bash
ollama pull gemma4
metis config set model.name gemma4
metis model check
```

Every model call is recorded as a `ModelAssistRecord`. Model output is always an advisory draft; it
can never promote, validate, retrieve, authorise, or revoke a fragment. See
[docs/local_model_runtime.md](docs/local_model_runtime.md).

## Develop

```bash
make dev        # editable install with dev and api extras
make test       # pytest, no live model needed
make lint       # ruff
make demo       # the end-to-end local demo
make regen      # rebuild the interactive demo and example outputs
make verify     # lint, test, and acceptance check
```

The test suite runs without a live model. To release to PyPI: `make build` (sdist and
wheel via `python -m build`, checked with twine), then `make publish` with a PyPI token. The
distribution is `metis-memory`; the import package and CLI are `metis`. `scripts/acceptance_check.py` checks the
project against its acceptance criteria, and the example expected-output files are generated from the
implementation by `scripts/generate_examples.py` so they never drift.

## What Metis is not

It is not a new protocol, a worker-surveillance system, an autonomous monitoring platform, a
production quality-management system, an agent framework, or a model-training pipeline. It is not a
vector database that retrieves by semantic similarity. It records no audio, video, biometrics,
screenshots, or keystrokes, and it never treats a fragment as ground truth. See
[ETHICAL_USE.md](ETHICAL_USE.md).

## Documentation

The [documentation index](docs/README.md) links the concept and reference docs: architecture, the
memory model, the governance model, condition-aware retrieval, the K1 to K17 taxonomy, the
`metis/1.0` profile, the CHAP integration, agent memory use, and the local model runtime. JSON
Schemas are in [schemas/](schemas/) and the runnable examples in [examples/](examples/).

## License

Apache-2.0. See [LICENSE](LICENSE).
