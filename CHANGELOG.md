# Changelog

All notable changes to TacitFlow are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.

## [0.1.0]

First public release.

### Added
- The TacitFlow domain model: typed `TacitFragment`, the K1 to K17 taxonomy, structured
  conditions, consent, evidence, three authority layers, and the validation state machine.
- The capture loop (Observe, Infer, Whisper, Confirm, Remember) with Tier-1 confirmation.
- Tier-2 Mission Group validation and the governance lifecycle: promote, reject, hold,
  re-elicit, revoke, supersede, with contestability.
- The condition-aware retrieval gate and the four-store memory model with a `MemoryBroker`.
- A local Ollama and Gemma model layer for bounded, advisory assistance, with deterministic
  fixtures so the demo and tests run without a live model.
- A Python adapter for CHAP: signed, append-only, hash-linked evidence, plus a compliance
  checker. Runs on CHAP (https://github.com/BrightbeamAI/chap), adds no new protocol.
- A Typer CLI, an optional FastAPI server, JSON Schemas, the `tacitflow/1.0` profile, whisper
  and model prompt libraries, and templates.
- Three runnable synthetic examples with expected outputs.
- An illustrated HTML explainer and an interactive HTML demo that drives the retrieval gate.
- A pytest suite (62 tests) that runs without a live model, plus an acceptance check script.
