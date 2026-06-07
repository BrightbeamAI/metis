# Local model runtime

TacitFlow uses a local model runtime for bounded, assistive tasks. It defaults to **Ollama** and the
**Gemma** family and must not call cloud LLM APIs.

## Install Ollama and pull a model

Install Ollama from <https://ollama.com>, start it (`ollama serve`), and pull a Gemma model:

```bash
ollama pull gemma4
```

## Configure TacitFlow

```bash
tacitflow config set model.provider ollama
tacitflow config set model.name gemma4
tacitflow config set model.url http://localhost:11434
tacitflow model check
```

Configuration is stored in `.tacitflow/config.json`. `tacitflow model check` reports whether Ollama
is reachable and whether the configured model is present.

## Which steps use model assistance

Assistance is bounded to: drafting low-burden whisper prompts, structuring a confirmed explanation
into a candidate fragment, classifying candidates into K1-K17, summarising operator confirmations,
suggesting structured conditions of applicability, drafting Mission Group review summaries, and
preparing agent-facing advisory wording from already-validated memory. The prompt templates live in
`prompts/model/`.

## Why model outputs remain suggestions

Every model call is recorded as a `ModelAssistRecord` (provenance, not authority) with
`human_review_required = true`. A model can never promote, validate, reject, revoke, authorise, or
retrieve a fragment, can never decide retrieval eligibility or authority layer, and is never treated
as ground truth. Governance, promotion, retrieval, and authority decisions are deterministic and
human-reviewed.

## Mocked / deterministic mode

The Ollama client fails gracefully when no server is present and, in deterministic mode (the demo
and test default), produces reproducible fixtures without any network call. The test suite passes
without a live Ollama server. The demo states clearly whether it used a live Gemma model or
deterministic fixtures.
