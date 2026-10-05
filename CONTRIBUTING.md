# Contributing to Metis

Thanks for your interest. Metis is a reference toolkit, so clarity and correctness come first.

## Ground rules

1. **Metis-first, CHAP underneath.** New collaboration mechanics reuse CHAP through
   `metis/integrations/chap/`: workspaces, tasks, whispers, reviews, control events, and the
   evidence chain all come from the reference coordinator. New `tacit.*` task or artefact kinds go
   into the `metis/1.0` profile.
2. **Governance stays deterministic and human-reviewed.** Local model assistance is advisory. Do
   not add a code path where a model promotes, validates, retrieves, authorises, or revokes a
   fragment.
3. **The audit chain is append-only.** Never add code that mutates or deletes evidence.
4. **No covert capture.** See [ETHICAL_USE.md](./ETHICAL_USE.md).

## Contribute a synthetic scenario

A useful first contribution is a small scenario written in plain English. Describe one cue from expert practice and the circumstances in which it matters. Use synthetic observations and fictional participants. 

Include the following details.

- The procedure and what the worker did.
- What the worker noticed and why it mattered.
- A short whisper and the worker's confirmation in their own words.
- The consent, provenance and conditions for use.
- The supporting evidence and a counterexample.
- The intended authority layer, Evidence, Advisory or Controlled, and the human review needed.
- A situation requiring escalation to a person.
- The expected effect of withdrawn consent or revocation.

A scenario describes a partial account of practice for people to review. Human validation and authority govern its use. Start with one scenario that a reviewer can understand and check. If you turn it into code, follow the development and verification steps below.

## Development

```bash
make dev          # editable install with the dev and api extras
make test         # pytest (no live Ollama needed)
make lint         # ruff check
make demo         # end-to-end local demo
make regen        # regenerate schemas, the interactive demo, and the example outputs
make verify       # lint, test, and the acceptance check
```

Schemas, `docs/demo.html`, and the example expected outputs are generated. After changing a model,
the gate, a scenario, or `scripts/demo_template.html`, run `make regen` and commit the results. A
test fails when a committed schema differs from its model, and a parity test checks the demo page's
JavaScript gate against the Python gate (it needs Node.js).

## Pull requests

- Add or update tests for any behaviour change.
- Run `make verify` before opening a PR.
- Keep modules focused; the package layout mirrors the domain: `fragment`, `taxonomy`,
  `conditions`, `consent`, `capture`, `validation`, `governance`, `retrieval`, `memory`, `models`,
  `audit`, and `integrations/chap`, with `storage` and `project.py` for local projects and `cli`,
  `api`, and `mcp` for the interfaces.
