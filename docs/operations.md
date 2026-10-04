# Running Metis in production

This guide is for the people who run a Metis server: upgrades, backups and restores, rotating
credentials, monitoring, incidents, retention, and capacity. It assumes a deployment set up as
[deploy/README.md](../deploy/README.md) describes.

## Upgrades

**Migrations.** A schema migration creates new tables, adds columns, and creates the ledger's
append-only triggers where they are missing. It runs in one transaction, and on PostgreSQL an
advisory lock serialises migrations started by several replicas at once. By default each server
migrates when it starts. To run servers with a database role that cannot change tables, set
`METIS_MIGRATE_ON_START=false` and run `metis server migrate` as the role that owns the tables,
before the new servers start; the Helm chart does this with `migrations.runAsJob`. A server
that does not migrate checks the schema on start and refuses to run against one it cannot use.

**Compatibility.** The database records its schema version and the oldest schema whose code can
use it. A release that only adds tables or columns keeps that floor, so a rolling update runs old
and new servers side by side, and rolling back the image works. A server older than the floor
refuses to start and says so: roll forward, or restore the backup taken before the upgrade. Each
workspace's domain state carries its own version as well: a server refuses a workspace written in
a newer format, and keeps any part of the state it does not know when it writes.

**Procedure.**

1. Back up the database (below), and read the changelog.
2. Deploy the new version. Watch `/readyz` and the logs while the pods roll.
3. Verify one busy workspace: `GET /v1/workspaces/{id}/audit/verify` returns `verified` and
   `ledger_agrees` as `true`.

## Backups and restores

**What to back up.** Every Metis table, from one consistent snapshot: `metis_workspaces`,
`chap_workspaces`, `metis_evidence_ledger`, `metis_members`, `metis_outbox`,
`metis_chat_identities`, and `metis_schema`. On PostgreSQL, `pg_dump` takes one consistent
snapshot, and point-in-time recovery works too. SQLite runs in write-ahead-log mode, so copy it
with `sqlite3 metis.db ".backup backup.db"` or a volume snapshot; the database file alone may lack
committed transactions. Keep the API keys file, the notifications and connectors files, and the
secrets with the backup.

**Restoring.** Restore the whole database from one snapshot: tables from different moments
disagree, and Metis refuses such a workspace as inconsistent. Each commit to a workspace carries a
unique token, so a running server notices that a restored workspace differs from the copy it
cached and rebuilds it from the database; restart the servers anyway, to drop their caches and
connection pools. Rebuilding a workspace verifies its chain and checks that its ledger holds as
many entries as the chain, ending with the same entry. Verify each workspace afterwards with
`GET /v1/workspaces/{id}/audit/verify`, which compares every entry.
Notifications queued when the backup was taken are delivered again.

## Rotating credentials

| Credential | How to rotate it |
| --- | --- |
| API key | Issue a new key under a new id (`metis server api-key create`), move the client to it, then revoke the old one (`metis server api-key revoke`). Servers reread the keys file when it changes; the file is written in one step, and a deleted file means no key is accepted. |
| OIDC signing keys | Nothing to do. Servers refetch the provider's key set every five minutes, so a key the provider removes stops being accepted within that time. For an emergency revocation, restart the servers. |
| Trusted-proxy secret | Change it in the proxy and in `METIS_TRUSTED_PROXY_SECRET`, then restart. Requests fail with 401 while the two differ, so change both together. |
| Slack, Teams, and webhook secrets; the database URL; the notifications and connectors files | Change the Secret, then restart the servers (a rolling restart). Each is read once at start. |

Keep one break-glass API key for a person with the global admin role
(`metis server api-key create --id break-glass --uri human:<you> --global-role admin`) in your
secret store: it works while the identity provider is down.

## Monitoring

**Probes.** `/healthz` answers while the process runs. `/readyz` answers when the database
replies within three seconds; it takes no workspace lock.

**Metrics.** `GET /metrics` (the Prometheus text format) and `GET /v1/admin/status` (JSON) report
the workspaces and the notifications in the outbox by status, with the age of the oldest still
waiting. Both need the global `metrics` role, which reads these counts and nothing else (the
global auditor may read them too): give your scraper an API key for a service, such as
`metis server api-key create --id prometheus --uri service:prometheus --global-role metrics`.
`metis server status` prints the same from the command line.

**Alert on:**

- `/readyz` failing;
- `metis_outbox_notifications{status="failed"} > 0`, or `metis_outbox_oldest_pending_seconds`
  above a few minutes;
- log lines `stored evidence is inconsistent`, `sweeping ... failed`, and `notification ... failed`;
- a rise in 503 responses (busy workspaces, an unreachable identity provider) or in 401
  responses.

**Logs.** Each request logs one line with its method, path, status, duration, the signed-in
participant, and a request id. A 5xx response carries the same request id in its body, so a
report from a user leads to the log line. Behind a reverse proxy, set `FORWARDED_ALLOW_IPS` to the
proxy's address so the server logs clients' addresses.

## Incidents

**Notifications do not arrive.** `metis server outbox list --status failed` lists them, with
each error naming the status and host that failed. Fix the channel, then send them again with
`metis server outbox retry`. A Teams whisper to someone who has not installed the Metis app is
retried for about an hour, then marked failed; the person can answer in the web app meanwhile.

**"Stored evidence for this workspace is inconsistent."** One workspace is refused; the others
keep working. Find the request id in the logs for the details. Compare the workspace's row in
`metis_workspaces`, its row in `chap_workspaces`, and its entries in `metis_evidence_ledger`. Fix
it by restoring that workspace's rows, all from one backup; the ledger refuses edits, so record
what was done and why.

**"This workspace was written by a newer version of Metis."** A newer server has written the
workspace. Upgrade this server.

**"The workspace is busy."** A long write holds the workspace, and requests that waited longer
than `METIS_LOCK_TIMEOUT_SECONDS` get 503 with `Retry-After`; clients retry. If it persists, look
for long transactions in the database (`pg_stat_activity`, and advisory locks in `pg_locks`).

**The identity provider is down.** OIDC sign-in answers 503 while its keys cannot be fetched;
API keys keep working. Use the break-glass key for administration.

## Retention and consent

The evidence chain is permanent by design: the CHAP chain and the evidence ledger keep every
record, including the words a worker confirmed, after the worker withdraws consent. Withdrawal
stops every further use of the fragment (no agent receives it again) and is itself recorded. The
ledger refuses updates and deletes, and no part of Metis deletes a workspace. Take these facts to
your data protection officer when you decide how you answer erasure requests and how long you keep
backups.

Notifications hold copies of some content (a whisper's question, for example). The sweep clears
delivered and failed notifications older than `METIS_OUTBOX_RETENTION_DAYS` (30 by default): a
notification is deleted, except that one which prevents a duplicate notice keeps only its key.
Where Metis reaches someone in Teams is forgotten when they remove the app.

## Capacity

- **Workspace size.** Each write stores the workspace's whole CHAP snapshot, and each rebuild
  (at start, and after another replica writes) restores and verifies the chain; both grow with the
  chain. A workspace per site, line, or team keeps writes fast.
- **Memory.** Each process keeps up to `METIS_ENGINE_CACHE_SIZE` workspaces in memory (64 by
  default); size the memory limit to your largest workspaces.
- **Database connections.** Each process holds up to `METIS_DB_POOL_SIZE` plus
  `METIS_DB_MAX_OVERFLOW` connections (5 and 10 by default). Give PostgreSQL enough for every
  replica, and the migration job.
- **Timeouts.** A workspace's writer waits at most `METIS_LOCK_TIMEOUT_SECONDS` (30) for its turn,
  and a statement in a workspace write runs at most `METIS_STATEMENT_TIMEOUT_SECONDS` (60).
- **Requests.** Bodies above `METIS_MAX_BODY_BYTES` (4 MiB) get 413; set your ingress to the same
  limit. An ingest request carries up to 1000 records, committed 50 at a time.
- **Background work.** On PostgreSQL one replica sweeps at a time; every replica delivers
  notifications, each leasing its own rows.
- **A live local model.** Drafting happens before a workspace is locked: up to two model calls
  for each capture and one for each answer, so other writers to the workspace proceed while the
  model works.

## A database role with least privilege

With migrations run by the owner (`METIS_MIGRATE_ON_START=false`), the servers can use a role
that changes data and never tables, and that can only append to the ledger. Create the role,
then name it to the migration in `METIS_DB_APP_ROLE` (Helm: `migrations.appRole`); each
`metis server migrate` then grants it exactly this:

```sql
GRANT SELECT ON metis_schema TO metis_app;
GRANT SELECT, INSERT, UPDATE ON metis_workspaces, chap_workspaces, metis_members TO metis_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON metis_outbox, metis_chat_identities TO metis_app;
GRANT SELECT, INSERT ON metis_evidence_ledger TO metis_app;
GRANT USAGE, SELECT ON SEQUENCE metis_outbox_id_seq TO metis_app;
```

The append-only triggers then guard the ledger against Metis itself, and the owner role, kept for
migrations, is the only one that can alter them.
