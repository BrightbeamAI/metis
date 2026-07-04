# Contributing to Metis

Thanks for your interest. Metis is a reference toolkit, so clarity and correctness
matter more than feature breadth.

## Ground rules

1. **Metis-first, CHAP underneath.** New collaboration mechanics should reuse CHAP
   (via `metis/integrations/chap/`), not introduce a parallel protocol.
2. **Governance stays deterministic and human-reviewed.** Local model assistance is
   only ever advisory. Do not add a code path where a model promotes, validates,
   retrieves, authorises, or revokes a fragment.
3. **The audit chain is append-only.** Never add code that mutates or deletes evidence.
4. **No covert capture.** See [ETHICAL_USE.md](./ETHICAL_USE.md).

## Development

```bash
make dev          # editable install with dev + api extras
make test         # pytest (no live Ollama needed)
make lint         # ruff check
make demo         # end-to-end local demo
```

## Pull requests

- Add or update tests for any behaviour change.
- Run `make lint` and `make test` before opening a PR.
- Keep modules focused; the package layout mirrors the domain
  (fragment / taxonomy / conditions / consent / capture / validation /
  governance / retrieval / memory / models / audit / integrations.chap).
