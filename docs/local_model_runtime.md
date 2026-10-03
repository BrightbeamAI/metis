# Local model runtime

Metis uses a local model runtime for bounded, assistive tasks. It defaults to **Ollama** and the
**Gemma** family, and it calls no cloud LLM API.

## Install Ollama and pull a model

Install Ollama from <https://ollama.com>, start it (`ollama serve`), and pull a Gemma model:

```bash
ollama pull gemma4
```

## Configure Metis

```bash
metis config set model.provider ollama
metis config set model.name gemma4
metis config set model.url http://localhost:11434
metis model check
```

Configuration is stored in the project's `config.json` (`./.metis/config.json` by default, or under
`$METIS_HOME`). `metis model check` reports whether Ollama is reachable and whether the configured
model is present. Run the demo with the live model using
`metis demo manufacturing-pump-vibration --live-model`, or try a single call with `metis model run`;
the other commands, the API, and the MCP server use deterministic fixtures.

## Which steps use model assistance

Assistance is bounded to: drafting low-burden whisper prompts, structuring a confirmed explanation
into a candidate fragment, classifying candidates into K1-K17, summarising operator confirmations,
suggesting structured conditions of applicability, drafting Mission Group review summaries, and
preparing agent-facing advisory wording from already-validated memory. The model prompt templates
live in `prompts/model/`, and the whisper templates in `prompts/whispers/`.

## Why model outputs remain suggestions

Every model call made during capture is recorded as a `ModelAssistRecord`, for provenance, with
`human_review_required = true`; `metis model run` makes one ad hoc call outside any workspace. A
fragment's provenance names a model only when one ran live; fixture output is recorded as
`deterministic_fixture`. Promotion, validation, rejection, revocation, authorisation, and retrieval
stay with people and the deterministic gate, and model output remains a draft until a person
accepts it.

## Mocked / deterministic mode

When no server is present, the Ollama client returns a deterministic fallback. In deterministic
mode (the demo and test default) it produces reproducible fixtures without any network call, so the
test suite passes without a live Ollama server. The demo states whether it used a live Gemma model
or deterministic fixtures.
