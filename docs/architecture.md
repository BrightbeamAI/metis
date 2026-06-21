# Architecture

TacitFlow follows one ordering principle: **TacitFlow domain model first, tacit memory second,
local AI assistance third, CHAP integration underneath.** No protocol machinery is duplicated.

## Layers

The **domain layer** (`fragment/`, `taxonomy/`, `conditions/`, `consent/`) defines what a tacit
fragment is: a typed `TacitFragment` with a K1-K17 category, structured conditions, provenance,
evidence, consent, an authority layer, a validation state, and use constraints. These models are
independent of CHAP but every one is serialisable as a CHAP artefact.

The **tacit memory layer** (`memory/`) promotes validated fragments into `TacitMemoryObject`s and
assembles an `AgentMemoryContext` through the `MemoryBroker`, combining the four memory stores.

The **local model layer** (`models/`) provides an Ollama client (default Gemma), prompt templates,
structured output models, and the `ModelAssistRecord`. It assists capture and structuring; it never
governs.

The **CHAP integration layer** (`integrations/chap/`) is the protocol foundation: an adapter that
drives the official `chap-coordinator` reference implementation. It dispatches JSON-RPC envelopes to a
real Coordinator, which owns the workspace, participants, tasks, and the append-only, hash-linked
evidence chain. The `CHAPAdapter` is the single object the rest of the toolkit uses to speak CHAP, so
moving to the reference implementation did not touch any domain code.

A thin façade, `TacitFlowEngine`, wires these together so the CLI, API, demo, and examples share one
orchestration path.

## The capture loop

`capture/` implements Observe → Infer → Whisper → Confirm → Remember. Each stage produces a CHAP
artefact (`tacit.capture_observation`, `tacit.inference_candidate`, `tacit.whisper_prompt`/
`tacit.whisper_response`, `tacit.operator_confirmation`, `tacit.fragment`) and an evidence entry.
Inference yields only a hypothesis; the fragment is created in the Evidence layer.

## The validation lifecycle

`validation/` holds the state machine and the Tier-1/Tier-2 records; `governance/` holds the
deterministic promotion policy and the `Governance` orchestrator. Tier-1 is descriptive fidelity
only. Tier-2 is a Mission Group decision over fourteen dimensions that sets the authority layer and
emits a `tacit.review_decision` plus the appropriate promotion/rejection/re-elicitation record. A
local model may draft the review summary; it never makes the decision.

## The retrieval gate

`retrieval/` implements condition-aware retrieval. The gate evaluates authority, validation,
consent, revocation, review/expiry, role, risk class, endogenous review, condition matching,
exclusions, and (for controlled) exact matching, in a fixed priority order, and emits a
`tacit.retrieval_decision`. It is not semantic search, and a model never decides eligibility.

## The memory broker

The `MemoryBroker` queries procedural, semantic, and episodic memory directly, and tacit memory only
through the gate. It returns an `AgentMemoryContext` that keeps the four memory types distinct and
records blocked tacit results (with reasons) for audit without exposing them as guidance.

## Audit and evidence flow

Every action flows through the `CHAPAdapter` into the evidence chain. `audit/` exports the chain to
portable JSONL and verifies it by independent replay (recomputing hashes and signatures). The chain
is append-only; corrections and revocations are appended, never rewritten.
