# CHAP integration

**Metis does not define its own protocol. It runs on CHAP, the Collaborative Human-Agent
Protocol** (<https://github.com/BrightbeamAI/chap>).

## What Metis uses

Metis depends on the official **`chap-coordinator`** Python reference implementation. The
integration layer in `metis/integrations/chap/` is a thin adapter (`CHAPAdapter`) that drives a
real `chap_coordinator.Coordinator`: it dispatches JSON-RPC envelopes and the Coordinator owns the
workspace, participants, tasks, and the append-only, hash-linked evidence chain. Metis reuses the
package's canonical JCS, id, and signing primitives directly, so it maintains no copy of the protocol
mechanics.

```python
from chap_coordinator import Coordinator, CoordinatorOptions
coord = Coordinator(CoordinatorOptions(deterministic_ids=True, deterministic_clock=True, enable_chain=True))
coord.dispatch({"jsonrpc": "2.0", "id": "1", "method": "workspace.create", "params": {"workspace": "wsp_demo"}})
```

`CHAPAdapter` is the single seam between Metis and CHAP. Because the rest of the toolkit talks only
to the adapter, adopting the reference implementation did not change any domain, capture, governance,
retrieval, or memory code.

## Which CHAP methods Metis dispatches

`workspace.create`, `participant.join`, `task.create`, `task.complete`, `whisper.ask`,
`whisper.answer`, `review.request`, `decide.approve` / `decide.reject` / `abstain.declare` /
`escalate.raise`, and `control.cancel` / `control.supersede`. Every one of these is implemented by the
reference Coordinator. `audit.read` is available for reading the chain.

## Mapping

| Metis concept | CHAP representation |
|-------------------|---------------------|
| Capture Cell | a workspace, created with `workspace.create` |
| Operator, Whisperer, Mission Group, Agent | participants, joined with `participant.join` |
| A produced record (observation, inference candidate, fragment, memory object, retrieval decision, model-assist record, promotion/rejection records) | a CHAP task created with `task.create` and completed with `task.complete`, carrying the artefact as the task output |
| Whisper prompt and answer | `whisper.ask` / `whisper.answer` |
| Operator confirmation (Tier-1) | a completed-task record artefact |
| Mission Group Tier-2 review | `review.request` then `decide.approve` / `decide.reject` (`abstain.declare` for hold, `escalate.raise` for re-elicit) |
| Revocation / supersession | `control.cancel` / `control.supersede`, plus the `tacit.revocation_record` / `tacit.supersession_record` |
| Audit trail | the Coordinator's append-only, hash-linked evidence chain |

The `tacit.*` names are CHAP task **kinds** and artefact **kinds** declared by the
[`metis/1.0` profile](../profiles/metis.md). CHAP is designed to be extended this way, so this
adds no new protocol.

## Integrity and conformance

The Coordinator is created with `enable_chain=True`, so each audit entry links to the previous by
`sha256( JCS(envelope) || prev_hash )`. `CHAPAdapter.verify()` and `metis.audit.replay` recompute
that linkage to confirm the chain has not been edited, including the head. Ed25519 per-message signing
is available through CHAP's optional `security-signed/1.0` profile.

`metis/integrations/chap/compliance.py` reads its method allow-list straight from the reference
Coordinator (`set(Coordinator()._handlers.keys())`). Metis therefore cannot dispatch a method the
reference does not implement: such a call would error and never be audited. This is a stronger
guarantee than the previous hand-rolled adapter could give.

## What stays Metis's

CHAP provides the collaboration and evidence layer. Metis owns everything that is about *tacit
practice*: the `TacitFragment` model and K1 to K17 taxonomy, structured conditions, consent, the
authority layers and validation state machine, the capture loop, Tier-1/Tier-2 governance, the
condition-aware retrieval gate, the four-store memory model, and the local model layer. None of those
are part of CHAP.
