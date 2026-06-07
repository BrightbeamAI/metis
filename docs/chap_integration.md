# CHAP integration

**TacitFlow does not define its own protocol. TacitFlow uses CHAP as the protocol foundation.**

CHAP (the Collaborative Human-Agent Protocol) lives at <https://github.com/BrightbeamAI/chap>.
TacitFlow validates against that specification and its JSON Schemas, and ships a Python adapter
under `tacitflow/integrations/chap/` rather than re-implementing the protocol.

## What we inspected

The supplied CHAP repository is the TypeScript reference for the Collaborative Human-Agent Protocol
(v0.2). We treated its specification, JSON Schemas, profile documents, and method catalogue as the
source of truth. The pieces that matter for TacitFlow:

- **Envelope** (`schemas/core/chap-envelope.schema.json`): every message carries `chap`, `id`
  (ULID), `ts`, `workspace` (`wsp_…`), `from`/`to` (participant URIs), `type`
  (request/response/notification), `method` (`namespace.verb`), `params`, and an `evidence`
  block with `prev_hash` and an Ed25519 `sig`.
- **Participants** (`chap-participant.schema.json`): URI schemes `human:`, `agent:`, `service:`,
  `group:`, `workspace:`, each with a JWK set.
- **Tasks and Artefacts** (`chap-task.schema.json`): tasks are `tsk_…`; artefacts are `art_…` with
  a `kind`, a `content_hash`, and, for implementation-defined kinds, a `schema` reference.
  `capture_fragment` is already a standard artefact kind.
- **Evidence chain** (`chap-evidence.schema.json`, SPECIFICATION §10): an append-only, per-workspace
  chain where `entry_n.prev_hash = SHA-256( JCS(envelope_{n-1} without evidence.sig) || sig_{n-1} )`,
  genesis `sha256:0…0`, signed with Ed25519 over the JCS (RFC 8785) canonicalisation.
- **Methods** (`schemas/profiles/chap-methods.schema.json`) across Core and the profile suite:
  `capture.append`, `whisper.ask`/`whisper.answer`, `review.request`/`decide.approve`/`reject`/
  `override`/`abstain.declare`/`escalate.raise`, `task.route`/`review.depth`/`escalate.auto`,
  `control.pause`/`resume`/`cancel`/`supersede`/`snapshot`/`rollback`, `handoff.propose`/`accept`/
  `decline`, and `audit.read`/`export`.

Because the reference is TypeScript (not Python-native), TacitFlow implements a faithful **Python
adapter** (`tacitflow/integrations/chap/`) that emits and validates CHAP-compatible records against
these structures. It reproduces the Ed25519 + JCS evidence chain exactly (see
`integrations/chap/canonical.py`, `crypto.py`, `evidence.py`) and a compliance checker
(`integrations/chap/compliance.py`) asserts that every envelope, artefact, and evidence entry
conforms, and that TacitFlow introduces no envelope keys or methods outside the CHAP catalogue.

## Mapping

| TacitFlow concept      | CHAP concept                                                      |
| ---------------------- | ----------------------------------------------------------------- |
| Capture Cell           | CHAP workspace with human, agent, service, and group participants |
| Operator               | CHAP human participant                                            |
| Whisperer agent        | CHAP agent participant using whisper capability                   |
| Mission Group          | CHAP group participant using review capability                    |
| Runtime Orchestrator   | CHAP coordinator plus routing/control/modes capabilities          |
| Tacit fragment         | CHAP artefact of kind `tacit.fragment`                            |
| Tacit memory object    | CHAP artefact of kind `tacit.memory_object`                       |
| Agent memory context   | CHAP artefact of kind `tacit.agent_memory_context`                |
| Local model assistance | CHAP artefact of kind `tacit.model_assist_record`                 |
| Operator confirmation  | CHAP artefact plus evidence entry                                 |
| Mission Group review   | CHAP review decision and evidence entry                           |
| Retrieval decision     | CHAP artefact of kind `tacit.retrieval_decision`                  |
| Revocation             | CHAP control event plus `tacit.revocation_record`                 |
| Handoff                | CHAP handoff capability                                           |
| Audit trail            | CHAP evidence chain                                               |

## Which CHAP capabilities are used, and why

- **Core** (workspace, participants, tasks, artefacts, evidence): the foundation for every action.
- **Whisper**: low-burden contextual probes during capture.
- **Review**: operator confirmation (Tier-1) and Mission Group decisions (Tier-2).
- **Routing**: retrieval and escalation decisions (`route_decision` shape).
- **Handoff**: shift and responsibility transfer (Example 3).
- **Control**: revoke, supersede, pause, rollback, lifecycle control.
- **Modes**: shadow / trial / production-style governance via the workspace mode and mode ceiling.
- **Security/signing**: Ed25519 signatures over JCS give stronger accountability (deterministic
  demo keys; real keys in production).
- **Audit / SCITT**: the exported JSONL chain is replayable and can be externally anchored.

Artefact *kinds* and task *kinds* prefixed `tacit.` are profile extensions (see
[tacitflow_profile.md](tacitflow_profile.md)), not new protocol, CHAP explicitly allows
implementation-defined artefact kinds with a `schema` reference.
