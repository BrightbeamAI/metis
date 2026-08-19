# Changelog

All notable changes to Metis are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.

## [0.1.2]

### Fixed
- Contestability works end to end: challenge, correct, withdraw, and re-elicitation
  requests are recorded as auditable events and escalate to the Mission Group, with
  test coverage for all four actions.
- `metis.__version__` now reports the installed package version.

### Changed
- Failures are never silent. The SQLite mirror and project initialisation warn on
  stderr when they cannot write; malformed whisper templates raise instead of being
  replaced by the generic wording.
- Deterministic engines produce byte-identical output across runs: every domain
  timestamp derives from the engine clock, so exported evidence chains and example
  files are reproducible.
- Importing `metis.api` no longer does any work; the demo engine is created on the
  first request.

### Removed
- Unused adapter parameters and an unused task-update method.

## [0.1.1]

### Fixed
- The PyPI project page now renders correctly (dedicated package description without repository-relative images).

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
- Runs on the official `chap-coordinator` Python reference implementation through a thin adapter;
  the Coordinator owns the append-only, hash-linked evidence chain and Metis adds no new protocol.
  The compliance check reads its method allow-list straight from the Coordinator.
- A Typer CLI, an optional FastAPI server, JSON Schemas, the `metis/1.0` profile, whisper
  and model prompt libraries, and templates.
- Three runnable synthetic examples with expected outputs.
- An illustrated HTML explainer and an interactive HTML demo that drives the retrieval gate.
- A pytest suite that runs without a live model, plus an acceptance check script.
