# CHAP integration

Metis records its collaboration and evidence with **CHAP, the Collaborative Human-Agent
Protocol** (<https://github.com/BrightbeamAI/chap>), through CHAP's reference coordinator, and
extends CHAP through the `metis/1.0` profile.

## What Metis uses

Metis depends on the official **`chap-coordinator`** Python reference implementation. The
integration layer in `metis/integrations/chap/` is a thin adapter (`CHAPAdapter`) that drives a
real `chap_coordinator.Coordinator`: it dispatches JSON-RPC envelopes, and the Coordinator owns the
workspace, participants, tasks, and the append-only, hash-linked evidence chain. Metis takes the
package's canonical JCS, identifier, and hashing primitives directly from it.

```python
from chap_coordinator import Coordinator, CoordinatorOptions
coord = Coordinator(CoordinatorOptions(deterministic_ids=True, deterministic_clock=True, enable_chain=True))
coord.dispatch({"jsonrpc": "2.0", "id": "1", "method": "workspace.create", "params": {"workspace": "wsp_demo"}})
```

`CHAPAdapter` is the single seam between Metis and CHAP: the domain, capture, governance,
retrieval, and memory code talk only to the adapter.

## Which CHAP methods Metis dispatches

`workspace.create`, `participant.join`, `task.create`, `task.complete`, `whisper.ask`,
`whisper.answer`, `review.request`, `decide.approve` / `decide.reject` / `abstain.declare` /
`escalate.raise`, and `control.cancel` / `control.supersede`. The reference Coordinator implements
every one of them.

## Mapping

| Metis concept | CHAP representation |
|-------------------|---------------------|
| Capture Cell | a workspace, created with `workspace.create` |
| Operator, Whisperer, Mission Group, assistant agent | participants, joined with `participant.join` |
| Mission Group reviewers | named human participants, listed as the reviewers of every Tier-2 review |
| A produced record (observation, inference candidate, fragment, memory object, retrieval decision, model-assist record, review, promotion, and rejection records, validation events) | a CHAP task of the artefact's kind, created with `task.create` and completed with `task.complete`, carrying the artefact as its output (the whisper prompt travels in `whisper.ask`) |
| A capture; a retrieval | a `tacit.capture` task assigned to the whisperer, on which the fragment's first Tier-2 review also runs; a `tacit.retrieve` task for the agent, with the `tacit.retrieval_decision` recorded against it |
| Whisper prompt and answer | `whisper.ask` / `whisper.answer` |
| Operator confirmation (Tier-1) | a `tacit.operator_confirmation` artefact |
| Mission Group Tier-2 review | `review.request` with the policy's rule (`quorum:2` by default), then one `decide.approve` per approving reviewer; `decide.reject` to reject, `abstain.declare` to hold, `escalate.raise` to re-elicit |
| Escalation to a person | a `tacit.escalation` task assigned to the operator, carrying the runtime context and the escalated fragments |
| Contest (challenge, correct, supersede, re-elicit) | a `tacit.validation_event` artefact, then a fresh `tacit.validate.tier2` or `tacit.re_elicit` task for the Mission Group |
| Revocation / supersession | `control.cancel` / `control.supersede`, plus the `tacit.revocation_record` / `tacit.supersession_record` |
| Audit trail | the Coordinator's append-only, hash-linked evidence chain |

CHAP's review rule does the counting. Under `quorum:2`, the review task completes when the second
distinct reviewer approves, and Metis promotes a fragment only after CHAP has completed its review.

The `tacit.*` names are CHAP task **kinds** and artefact **kinds** declared by the
[`metis/1.0` profile](../profiles/metis.md). CHAP is designed to be extended this way.

## Integrity and conformance

The Coordinator is created with `enable_chain=True`, so each audit entry links to the previous by
`sha256( JCS(envelope) || prev_hash )`. `CHAPAdapter.verify()` recomputes that linkage up to the
head the store records, and `metis.audit.replay` recomputes it for an exported or ledger file. Ed25519 per-message signing is
available through CHAP's optional `security-signed/1.0` profile.

`metis/integrations/chap/compliance.py` reads its method allow-list straight from the reference
Coordinator (`set(Coordinator()._handlers.keys())`), so the allow-list always matches the installed
version. A method the reference does not implement fails at dispatch, before anything reaches the
evidence chain.

## Persistence

A local project passes CHAP's `SqliteStore` (`chap.db`) to the Coordinator, which saves the
workspace after each entry and restores it on the next start. The adapter reattaches to a restored
workspace and rebuilds its view of participants, tasks, artefacts, and pending whispers, so the
chain continues where it stopped.

The Coordinator keeps dispatching when a save fails, by design, so Metis also appends every entry
to the workspace's own ledger (`evidence.jsonl`) after each dispatch, flushed to disk. Opening a
workspace runs a quick check of the ledger against the restored chain (entry count and the last
link) and stops with an error if they disagree; `metis audit verify` compares them entry for
entry.

## What stays Metis's

CHAP provides the collaboration and evidence layer. Metis owns everything that is about *tacit
practice*: the `TacitFragment` model and K1 to K17 taxonomy, structured conditions, consent, the
authority layers and validation state machine, the capture loop, Tier-1/Tier-2 governance, the
condition-aware retrieval gate, the four-store memory model, and the local model layer. These sit
in Metis and reach CHAP as tasks, artefacts, and decisions.
