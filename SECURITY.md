# Security

Metis runs on infrastructure you control: a laptop for the toolkit, or your own servers and
database for the multi-user server. By default it contacts no cloud service or external model API.

## Reporting a vulnerability

For anything that could expose worker data or break the audit chain, please open a private
security advisory on GitHub or email the maintainers, so the issue can be fixed before it is
public.

## Security-relevant design notes

- **Append-only evidence.** Metis records every governance action as a
  CHAP evidence entry in the official chap-coordinator's append-only, hash-linked chain.
  Corrections and revocations are appended as new entries, and recorded history stays as it was.
  A local project persists the coordinator in CHAP's SQLite store and keeps a per-workspace
  ledger that is appended and flushed as each entry is recorded. Opening a workspace runs a quick
  check of the ledger against the store, and `metis audit verify` compares the two entry for
  entry, so an edit to the ledger shows up as a disagreement.
- **One writer per workspace.** A process writing a workspace holds an exclusive lock, so two
  processes cannot overwrite each other's evidence; domain state is saved to SQLite in one
  transaction. Read-only opens record nothing.
- **Integrity.** The chain links each entry by `sha256( JCS(envelope) || prev_hash )`. Verifying
  the chain up to the head the CHAP store records detects any later edit to a recorded envelope.
  Ed25519 per-message signing is available through CHAP's optional `security-signed/1.0` profile
  for stronger non-repudiation.
- **No secret material in fragments.** Do not place credentials, tokens, or personal
  identifiers in fragment content. Provenance identifies participants by URI, such as
  `human:operator@plant_a`.
- **Local models.** The Ollama client talks to the configured model runtime,
  `http://localhost:11434` by default; keep it pointed at a local server. When no server is
  present it returns a deterministic fallback, so the demo and tests run offline.

## Threat model boundaries

Metis governs how tacit fragments are captured, validated, and retrieved.

- **The Metis server** (`metis server run`) is the multi-user deployment. Every request acts as
  the identity its credentials prove: an OIDC access token verified against the provider's keys,
  an API key stored only as a SHA-256 hash, or a trusted proxy's headers accompanied by a shared
  secret. Roles in each workspace decide what a caller may do, and every role change is recorded
  on the workspace's chain. Requests run in database transactions with one writer per workspace,
  and the evidence ledger table refuses updates and deletes. Serve it over HTTPS through an
  ingress or reverse proxy, and keep the database, the API keys file, and the identity
  provider's configuration in your secret store.

- **The FastAPI server** (`metis.api`) is a single-user reference server. It has no
  authentication and records the identities callers supply, so run it on localhost only. Every
  review it records names its reviewers (`decided_by`).
  Audit exports are confined to the project's `exports/` directory and accept a plain
  filename, so a request cannot choose where the server writes.
- **The MCP server** (`metis mcp`) runs over stdio for one local client. It checks the form
  of identities (`human:` or `agent:`), and the client vouches for who is speaking. No MCP tool
  can review, promote, or authorise a fragment, and agents learn of unauthorised fragments only
  as a count.
- **Identity in deployments.** Mission Group approvals, worker answers, and contests are
  only as trustworthy as the identities behind them. Put authenticated identity between
  people and these interfaces before relying on them for real decisions.
