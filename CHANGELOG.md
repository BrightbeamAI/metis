# Changelog

All notable changes to Metis are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.

## [0.1.3]

### Added
- An MCP server (`metis mcp`, optional `mcp` extra) that serves governed tacit memory to any
  MCP client. Agents receive guidance only through the retrieval gate, learn of unauthorised
  fragments only as a count, and have no tool that reviews, promotes, or authorises.
- Persistent local projects. The CLI keeps the CHAP coordinator in CHAP's SQLite store, so a
  workspace's evidence chain continues across commands, and writes a per-workspace append-only
  ledger. Each scenario run gets its own workspace. New commands: `metis workspace list | use |
  describe`, `metis audit verify`, and `metis mcp`.
- Escalation to a person. High-risk situations and near misses (same equipment, different
  situation) open a `tacit.escalation` task and add a required human action.
- SQLite is the authoritative store for each workspace's domain state (fragments, memory
  objects, memory entries, pending captures), saved in one transaction and queryable with SQL.
- One writer per workspace across processes, with read-only inspection and verification
  alongside a running writer such as `metis mcp`.
- Two-step capture: `begin_capture` asks the worker, `answer_whisper` records the worker's
  own answer and consent. Only the addressed human worker may answer.
- Whisper budgets that ration prompts per worker and record deferrals.
- A `ValidationEvent` model and schema for whisper deferrals, declined consent, and contests.
- Re-review of fragments in use. The Mission Group can renew a fragment (for example after its
  review date), move it between Advisory and Controlled, hold it, reject it, or send it back for
  re-elicitation. The fragment stays in use until the decision, a later promotion rebuilds its
  memory object under the same id, and `MetisEngine.request_review` opens a review ahead of time.
- Knowledge Audit and Critical Decision Method interview guides.

### Changed
- Promotion is a collective decision: a quorum of named Mission Group reviewers
  (`quorum:2` by default), enforced by CHAP. One reviewer can hold, reject, or re-elicit.
- Promotion sets a review date and expiry triggers; the gate blocks fragments past review.
- Fragment confidence is derived from the recorded evidence: its strength, recurrence, outcome
  link, and counterexamples.
- The retrieval gate decides applicability before risk, so escalations cover the fragments that
  apply and the near misses.
- Provenance names a model only when one ran, review status follows the fragment's state,
  and every lineage entry links to its evidence-chain record.
- Only the worker who contributed a fragment can withdraw consent; reviewers retire
  fragments with `revoke`.
- Every contest except a withdrawal joins the fragment's open review or opens one, and the
  reviewers decide it with a Tier-2 decision.
- Clearer wording in whisper templates, inference hypotheses, gate rationales, escalation
  actions, and agent instructions.
- Each JSON Schema file is named after the artefact kind whose `schema` URI points to it:
  `tacit_agent_memory_context` and `tacit_model_assist_record` replace `agent_memory_context` and
  `model_assist_record`, and review decisions have their own `tacit_review_decision` schema.
- Requires `chap-coordinator` 0.2.13 or later (below 0.3).
- The local project layout is new: run `metis demo` again to create a project in this layout.

### Fixed
- Records created through the API or another live engine carried the deterministic demo
  clock. Timestamps now come from the engine making the call, and live engines use real time.
- A held fragment can be reviewed again.
- Capture validates the category before recording anything, so an unknown category leaves the
  evidence chain unchanged.
- The API's `/promote` accepts only promotion outcomes, and `/audit/export` writes only inside
  the project's `exports/` directory.
- The `tacit_validation_event` schema describes validation events.
- When a worker confirms without adding words, the fragment holds the candidate they confirmed,
  and the deterministic summary fixture restates that text.

## [0.1.2]

### Fixed
- Contestability works end to end: challenge, correct, withdraw, and re-elicitation
  requests are recorded as auditable events and escalate to the Mission Group, with
  test coverage for all four actions.
- `metis.__version__` reports the installed package version.

### Changed
- Failures are reported. The SQLite mirror and project initialisation warn on stderr when
  they cannot write, and a malformed whisper template raises an error.
- Deterministic engines produce byte-identical output across runs: every domain
  timestamp derives from the engine clock, so exported evidence chains and example
  files are reproducible.
- Importing `metis.api` has no side effects; the demo engine is created on the first request.

### Removed
- Unused adapter parameters and an unused task-update method.

## [0.1.1]

### Fixed
- The PyPI project page renders correctly (dedicated package description without repository-relative images).

## [0.1.0]

First public release.

### Added
- The Metis domain model: typed `TacitFragment`, the K1 to K17 taxonomy, structured
  conditions, consent, evidence, three authority layers, and the validation state machine.
- The capture loop (Observe, Infer, Whisper, Confirm, Remember) with Tier-1 confirmation.
- Tier-2 Mission Group validation and the governance lifecycle: promote, reject, hold,
  re-elicit, revoke, supersede, with contestability.
- The condition-aware retrieval gate and the four-store memory model with a `MemoryBroker`.
- A local Ollama and Gemma model layer for bounded, advisory assistance, with deterministic
  fixtures so the demo and tests run without a live model.
- Uses the official `chap-coordinator` Python reference implementation through a thin adapter;
  the Coordinator owns the append-only, hash-linked evidence chain, and Metis extends CHAP through
  the `metis/1.0` profile. The compliance check reads its method allow-list straight from the
  Coordinator.
- A Typer CLI, an optional FastAPI server, JSON Schemas, the `metis/1.0` profile, whisper
  and model prompt libraries, and templates.
- Three runnable synthetic examples with expected outputs.
- An illustrated HTML explainer and an interactive HTML demo that drives the retrieval gate.
- A pytest suite that runs without a live model, plus an acceptance check script.
