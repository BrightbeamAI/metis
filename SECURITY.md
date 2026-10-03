# Security

Metis is a local-first reference toolkit. It does not require, and by default does
not contact, any cloud service or external model API.

## Reporting a vulnerability

Please open a private security advisory or email the maintainers rather than filing a
public issue for anything that could expose worker data or break the audit chain.

## Security-relevant design notes

- **Append-only evidence.** Metis records every governance action as a
  CHAP evidence entry in the official chap-coordinator's append-only, hash-linked chain.
  History is never rewritten; corrections and revocations are appended. A local project
  persists the coordinator in CHAP's SQLite store and keeps a per-workspace ledger that is
  appended and flushed as each entry is recorded; on open, ledger and store are checked
  against each other, and `metis audit verify` detects any edit to the ledger.
- **One writer per workspace.** A process writing a workspace holds an exclusive lock, so two
  processes cannot overwrite each other's evidence; domain state is saved to SQLite in one
  transaction. Read-only opens record nothing.
- **Integrity.** The chain links each entry by `sha256( JCS(envelope) || prev_hash )`, so any later
  edit to a recorded envelope is detectable by replaying the chain. Ed25519 per-message signing is
  available through CHAP's optional `security-signed/1.0` profile for stronger non-repudiation.
- **No secret material in fragments.** Do not place credentials, tokens, or personal
  identifiers in fragment content. Provenance references participants by URI, not by
  personal data.
- **Local models.** The Ollama client talks only to a local model runtime
  (default `http://localhost:11434`). It fails gracefully (and deterministically in
  tests) when no server is present.

## Threat model boundaries

Metis governs how tacit fragments are captured, validated, and retrieved. It does
not provide authentication, authorisation, or transport security for a multi-tenant
deployment; those are the responsibility of the surrounding CHAP Coordinator and host
environment.

- **The FastAPI server** (`metis.api`) is a single-user reference server. It has no
  authentication and records the identities callers supply, so run it on localhost only.
  Audit exports are confined to the project's `exports/` directory and accept a plain
  filename, so a request cannot choose where the server writes.
- **The MCP server** (`metis mcp`) runs over stdio for one local client. It checks the form
  of identities (`human:` or `agent:`), not who supplies them. No MCP tool can review,
  promote, or authorise a fragment, and unauthorised fragments are never identified to agents.
- **Identity in deployments.** Mission Group approvals, worker answers, and contests are
  only as trustworthy as the identities behind them. Put authenticated identity between
  people and these interfaces before relying on them for real decisions.
