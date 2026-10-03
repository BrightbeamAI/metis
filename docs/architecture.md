# Architecture

Metis follows one ordering principle: **Metis domain model first, tacit memory second,
local AI assistance third, CHAP integration underneath.** Every protocol concept comes from CHAP.

## Layers

The **domain layer** (`fragment/`, `taxonomy/`, `conditions/`, `consent/`) defines what a tacit
fragment is: a typed `TacitFragment` with a K1-K17 category, structured conditions, provenance,
evidence, consent, an authority layer, a validation state, and use constraints. These models are
independent of CHAP but every one is serialisable as a CHAP artefact.

The **tacit memory layer** (`memory/`) promotes validated fragments into `TacitMemoryObject`s and
assembles an `AgentMemoryContext` through the `MemoryBroker`, combining the four memory stores.

The **local model layer** (`models/`) provides an Ollama client (default Gemma), prompt templates,
structured output models, and the `ModelAssistRecord`. It assists capture and structuring; people
make the governance decisions.

The **CHAP integration layer** (`integrations/chap/`) is the protocol foundation: an adapter that
drives the official `chap-coordinator` reference implementation. It dispatches JSON-RPC envelopes to a
real Coordinator, which owns the workspace, participants, tasks, and the append-only, hash-linked
evidence chain. The `CHAPAdapter` is the single object the rest of the toolkit uses to speak CHAP, so
the domain code depends only on the adapter's small surface.

A thin façade, `MetisEngine`, wires these together so the CLI, the API, the MCP server, the demo,
and the examples share one orchestration path.

## The capture loop

`capture/` implements Observe → Infer → Whisper → Confirm → Store. Each stage produces a CHAP
artefact (`tacit.capture_observation`, `tacit.inference_candidate`, `tacit.whisper_prompt`/
`tacit.whisper_response`, `tacit.operator_confirmation`, `tacit.fragment`) and an evidence entry.
Inference yields a hypothesis for the worker to confirm or correct; the fragment is created in the
Evidence layer.

The loop runs in two halves. `MetisEngine.begin_capture` observes, infers, and asks the worker one
whisper; `MetisEngine.answer_whisper` records the worker's own answer, which only the addressed
human worker may give, and stores the fragment. Pending captures persist with the workspace, so a
worker can answer after a restart. Whispers are rationed per worker (`WhisperBudget`, five per
eight hours by default); a capture beyond the budget is deferred and the deferral recorded.

## The validation lifecycle

`validation/` holds the state machine and the Tier-1/Tier-2 records; `governance/` holds the
deterministic promotion policy and the `Governance` orchestrator. Tier-1 checks descriptive
fidelity: the worker confirms that the fragment says what they meant. Tier-2 is a Mission Group
decision over fidelity, operational relevance, normative alignment, risk, evidence, conditions, and
consent. It sets the authority layer and emits a `tacit.review_decision` plus the matching
promotion, rejection, or re-elicitation record. Promotion needs a quorum of named reviewers
(`quorum:2` by default), which CHAP's review rule enforces; one reviewer can hold, reject, or
re-elicit. A fragment in use is re-reviewed in place on a fresh review task: it stays in use until
the reviewers renew it, change its layer, hold it, reject it, or re-elicit it, and a later
promotion rebuilds its memory object under the same id. A local model may draft the review
summary; the reviewers decide.

## The retrieval gate

`retrieval/` implements condition-aware retrieval. The gate evaluates revocation, consent,
endogenous review, authority, validation, review date, role, conditions and exclusions, controlled
exactness, and risk class, in that order, and emits a `tacit.retrieval_decision`. Applicability is
decided before risk, so a fragment that does not apply is reported with the condition that failed.
High-risk situations and near misses open a `tacit.escalation` task for a person. Eligibility
comes from recorded conditions, consent, and authority, and the gate is deterministic (see
[condition_aware_retrieval.md](condition_aware_retrieval.md)).

## The memory broker

The `MemoryBroker` queries procedural, semantic, and episodic memory directly, and tacit memory only
through the gate. It returns an `AgentMemoryContext` that keeps the four memory types distinct,
records blocked tacit results with their reasons in the audit trail, and keeps them out of the
guidance.

## Audit and evidence flow

Every action flows through the `CHAPAdapter` into the evidence chain. `audit/` exports the chain to
portable JSONL and verifies it by independent replay (recomputing the hash links). The chain is
append-only: corrections and revocations are new entries, and recorded entries stay as they were.

## Persistence

A local project (`metis/project.py`, `$METIS_HOME`) keeps the CHAP coordinator in its SQLite store
(`chap.db`), so every command reopens a workspace and continues its chain. Each workspace keeps its
domain state (fragments, memory objects, the procedural, semantic, and episodic entries, pending
captures, counters) in its own SQLite database (`metis.db`), saved in one transaction so a crash
leaves either the previous state or the new one, complete. Fragment rows carry category, layer, and
state as columns, so the store answers SQL queries directly.

Each workspace also has an append-only ledger (`evidence.jsonl`): the adapter appends each new
evidence entry as it is recorded and flushes it to disk. On open, a quick check compares the
ledger with the CHAP store (entry count and the last link) and stops with an error on a lost
write; `metis audit verify` compares the two entry for entry. The ledger refuses to append if
another writer has touched it.

A workspace has one writer at a time. A process that opens a workspace for writing holds an
exclusive lock (`.lock`) until it exits; another process that tries to write the same workspace is
refused with a clear message. Read-only opens take no lock and record nothing, so inspection and
`metis audit verify` work while a writer such as `metis mcp` runs. Running another scenario creates
a new workspace, so earlier runs stay intact.

## Timestamps

Every timestamp in a record comes from `metis/clock.py`. A deterministic engine binds its
coordinator clock for the duration of its own calls only, so the generated examples, the demo
page's data, and the tests are byte-stable, while live engines (the CLI, including `metis demo`,
the API, and the MCP server) always record real time.
