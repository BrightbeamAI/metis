# Changelog

All notable changes to Metis are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.

## [0.1.5]

### Added
- The Metis server (`metis server run`, extras `server` and `postgres`): a multi-user HTTP API in
  which every identity comes from sign-in (OIDC access tokens, hashed API keys, or a trusted
  proxy), workspace roles decide each action, and each request commits its domain state, CHAP
  chain, and evidence ledger together. See docs/server.md.
- Workspace membership: members hold the worker, reviewer, agent, capture, escalation, auditor,
  and admin roles, recorded on the chain as `tacit.membership_record`. The Mission Group is the
  set of reviewer members, and a new reviewer joins the reviews already open.
- Per-reviewer votes (`MetisEngine.cast_review_vote`): each reviewer records their own decision,
  the first approval proposes the promotion and its use constraints, and the promotion is
  applied when the approvals meet the review rule.
- The SQL workspace repository for PostgreSQL and SQLite, with one writer per workspace, one
  CHAP snapshot per transaction, and an append-only ledger table.
- `metis server` administration commands for workspaces, members, and API keys.
- A container image, a Docker Compose stack with PostgreSQL and Keycloak, and a Helm chart. See
  deploy/README.md.
- The web app at `/app` and `GET /v1/me/inbox`: workers answer whispers and manage their
  contributions, reviewers vote, and escalation handlers decide, across their workspaces.
- Escalation decisions (`MetisEngine.decide_escalation`, recorded as `tacit.escalation_decision`):
  the guidance applies, does not apply, or goes to the reviewers.
- Whisper deadlines: an unanswered whisper lapses at its deadline (`lapse_whispers`, a
  `whisper_lapsed` validation event), swept by the server or `metis server sweep`.
- Notifications by email, Slack, Microsoft Teams, and signed webhooks, planned inside each
  write's transaction, kept in an outbox, and delivered with retries.
- Remote MCP at `/mcp`: stateless streamable HTTP, signed in per request, with tools for agents
  and capture sources under their workspace roles.
- `metis.client`: `MetisClient` and `AsyncMetisClient` for the server API, with API keys, access
  tokens, or OAuth client credentials, and `wait_for_escalation`.
- Agent framework adapters: function tools for the OpenAI and Anthropic APIs
  (`metis.integrations.agent_tools`), and LangChain tools and a retriever
  (`metis.integrations.langchain`). See docs/agent_integrations.md.
- Capture connectors: source mappings (`METIS_CONNECTORS_FILE`) turn records from workplace
  systems into observations through `POST /v1/workspaces/{id}/ingest/{source}` or
  `metis connector import`, each record captured once.
- Whispers in Slack (direct messages with answer buttons and a correction form) and Microsoft
  Teams (Adaptive Cards from the Metis bot, for the tenants you name), answered in place and
  recorded as the worker. See docs/connectors.md.
- Operating the server: `GET /metrics` and `GET /v1/admin/status` for a global `metrics` role
  (or the global auditor), `metis server status`, `metis server outbox retry`, notification
  retention (`METIS_OUTBOX_RETENTION_DAYS`), schema migrations that can run as a separate job
  (`METIS_MIGRATE_ON_START`) and grant the servers' own role only what it needs
  (`METIS_DB_APP_ROLE`), and docs/operations.md.
- Limits: request bodies (`METIS_MAX_BODY_BYTES`), every text field (`metis.limits`), and
  workspace lock and statement timeouts that answer 503 with `Retry-After`.
- `draft_capture` and `draft_confirmation`: a server asks the local model before it locks a
  workspace, and passes the drafts to `begin_capture` and `answer_whisper`.
- `RetrievalDecision.escalation_decisions`: the fragments given because a person decided an
  escalation of the same situation, written only when there are some.

### Changed
- A reviewer does not decide on a fragment they contributed.
- A retrieval that escalates reuses its requester's open escalation of the same situation, and a
  person's decision holds for that requester and situation for `escalation_grant_hours` (12 by
  default): guidance a person said applies is given, and guidance they said does not apply stays
  withheld without asking again.
- Domain state from a newer Metis is refused, and state keys an engine does not know are kept
  when it writes.
- The README leads with figures from metis.brightbeam.works and keeps the text to what a reader
  needs. The PyPI description gives each figure's alt text in its place.
- Paper links, including the PyPI project link and the citation file's URL, point to the PDF on
  metis.brightbeam.works.
- `retrieve` and `agent_context` record the asking agent (`requester`), `begin_capture` records
  who reported an observation (`submitted_by`), and the whisper deadline is configurable.
- A promotion with no use constraints gives the fragment the memory object's default
  constraints, so the gate and the memory object agree.

## [0.1.4]

### Added
- Re-review of fragments in use. The Mission Group can renew a fragment (for example after its
  review date), move it between Advisory and Controlled, hold it, reject it, or send it back for
  re-elicitation. The fragment stays in use until the decision, a later promotion rebuilds its
  memory object under the same id, and `MetisEngine.request_review` opens a review ahead of time.
- Re-capture after re-elicitation: `begin_capture`, `capture_observation`, and the API's
  `/capture` take `supersedes=<fragment id>`, and the confirmed replacement supersedes the
  fragment the Mission Group sent back.

### Changed
- Every contest except a withdrawal joins the fragment's open review or opens one, and the
  reviewers decide it with a Tier-2 decision.
- Live engines (a local project, the API, and the MCP server) record a Tier-2 decision only when
  it names its reviewers in `decided_by`; the API's `/review` answers 422 otherwise.
  Deterministic engines keep filling in the configured members for demos and tests.
- Memory objects follow their fragment's layer and state, and the MCP listing shows fragments
  in use and inside their review date.

### Fixed
- A decision that names more reviewers than the review rule needs records the approvals CHAP
  counts and completes the review.
- Revoking or superseding a fragment cancels any review still open on it, and a revoked
  fragment stays out of review.
- The API's `/capture` answers 422 for invalid input.

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
