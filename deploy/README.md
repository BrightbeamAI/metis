# Deploying the Metis server

The Metis server runs Metis for many people and agents at once. Everyone signs in, each
workspace decides what its members may do, and every capture, review, and retrieval is
recorded on the workspace's CHAP evidence chain. The [server guide](../docs/server.md)
describes the API and the roles; this page covers running it.

| Path | What it is |
| --- | --- |
| [`../Dockerfile`](../Dockerfile) | The server image: `metis server run` on port 8000 as a non-root user |
| [`compose/`](compose/) | PostgreSQL, Keycloak, and Metis on one machine, for development and evaluation |
| [`helm/metis/`](helm/metis/) | A Helm chart for Kubernetes |

## Try it on one machine

You need Docker with Compose, `curl`, and `python3`.

```bash
docker compose -f deploy/compose/docker-compose.yml up -d --build
sh deploy/compose/try-it.sh
```

The script signs in as five people and two agents and walks one fragment through the whole
loop: a maintenance-system connector reports what a worker did differently, the worker confirms
the account and grants consent, two reviewers promote it, an agent receives it as guidance, and
an auditor verifies the evidence chain.

The stack exposes these services on `127.0.0.1`:

| Service | Address | Notes |
| --- | --- | --- |
| Metis web app | http://localhost:8000/app | Sign in as one of the people below |
| Metis API | http://localhost:8000/docs | The interactive API reference |
| Mailpit | http://localhost:8025 | The notification emails Metis sends |
| Keycloak | http://localhost:8080 | Realm `metis`; console user `admin`, password `admin-dev-only` |
| PostgreSQL | localhost:5432 | Database `metis`, user `metis`, password `metis-dev-only` |

After `try-it.sh`, sign in to the web app as `wendy` or `rhea` to see the inbox, and open Mailpit
to read the notifications each step sent.

The `metis` realm has five people, each with the password `<name>-dev-only`: `ana` (global
admin), `wendy`, `rhea`, `raj`, and `audrey` (global auditor). Workspace roles come from each
workspace's membership, so Ana creates a workspace and names its members. The `shift-assistant`
client signs in with its own credentials as the agent `agent:shift-assistant`.

Get a token for a person, or for the agent:

```bash
TOKEN_URL=http://localhost:8080/realms/metis/protocol/openid-connect/token
curl -s -d grant_type=password -d client_id=metis-cli -d username=ana -d password=ana-dev-only $TOKEN_URL
curl -s -d grant_type=client_credentials -d client_id=shift-assistant \
     -d client_secret=shift-assistant-dev-only $TOKEN_URL
```

Issue an API key for a connector or another agent; the server reads new keys on the next
request:

```bash
docker compose -f deploy/compose/docker-compose.yml exec metis \
  metis server api-key create --id cmms --uri agent:cmms-connector
```

These credentials are for a local machine only. Remove the stack and its data with
`docker compose -f deploy/compose/docker-compose.yml down -v`.

## Run it in production

1. **Use PostgreSQL.** Point `METIS_DATABASE_URL` at it. The server creates and upgrades its
   tables on start; to run it with a role that cannot change tables, set
   `METIS_MIGRATE_ON_START=false` and run `metis server migrate` as the owner first (see the
   [operations guide](../docs/operations.md#a-database-role-with-least-privilege)). Several
   replicas can share the database: each workspace's writes are serialised through a PostgreSQL
   advisory lock. SQLite suits a single replica with a persistent volume.
2. **Connect your identity provider.** Register an API audience (for example `metis-api`) and
   set `METIS_OIDC_ISSUER` and `METIS_OIDC_AUDIENCE`. People sign in as `human:<email>`; a client
   using its own credentials signs in as `agent:<client id>`. Name the claim that carries roles
   in `METIS_OIDC_ROLES_CLAIM` (`realm_access.roles` for Keycloak, `roles` for Entra ID app
   roles, `groups` for Okta), and grant the `metis-admin` and `metis-auditor` roles to the people
   who hold them. A token whose email is marked unverified names the person by subject instead;
   set `METIS_OIDC_REQUIRE_EMAIL_VERIFIED=true` when your provider marks verified emails, and point
   `METIS_OIDC_ISSUER` at your own tenant (Entra ID), so only your directory's emails count.
3. **Name the first administrator.** `METIS_ADMINS=human:ana@example.com` grants the global admin
   role, so Ana can create the first workspaces before roles are set up in the provider.
4. **Issue API keys for software that cannot use OIDC.** `metis server api-key create` prints a key
   once and stores only its hash in the keys file (`METIS_API_KEYS_FILE`). Keep the file in a
   secret store.
5. **Terminate TLS in front of the server.** Run Metis behind an ingress or reverse proxy that
   serves HTTPS, applies your rate limits, and limits request bodies to `METIS_MAX_BODY_BYTES`
   (4 MiB by default). To let the proxy sign people in instead (for example oauth2-proxy), set
   `METIS_TRUSTED_PROXY_SECRET` to a secret the proxy sends in `X-Metis-Proxy-Secret`, and have
   the proxy set the identity headers itself, replacing any a client sends.
6. **Set up the web app and notifications.** Register a public client for the web app with the
   redirect URI `<public URL>/app` and the API audience, then set `METIS_UI_CLIENT_ID` and
   `METIS_PUBLIC_URL`. Configure email, Slack, Teams, or webhooks as the
   [server guide](../docs/server.md#notifications) describes.
7. **Connect workplace systems and chat tools.** Map each source of records in
   `METIS_CONNECTORS_FILE` and give it a capture identity; set the Slack or Teams credentials to
   put whispers in chat. The [connectors guide](../docs/connectors.md) covers both.
8. **Back up, monitor, and plan for incidents.** The database holds every workspace's domain
   state, CHAP chain, and evidence ledger; the ledger table refuses updates and deletes. The
   [operations guide](../docs/operations.md) covers backups and restores, upgrades, rotating
   credentials, the metrics to alert on, and runbooks.
9. **Partition busy workspaces.** Each write stores the workspace's full CHAP snapshot, so its
   cost grows with the length of the chain. A workspace per site, line, or team keeps chains to
   a size that writes in milliseconds.

## Configuration

Every setting is an environment variable. The server reads them at start.

| Variable | Default | Meaning |
| --- | --- | --- |
| `METIS_DATABASE_URL` | `sqlite:///./.metis/server.db` | `postgresql://user:password@host/db` or `sqlite:///path` |
| `METIS_OIDC_ISSUER` | | The provider's issuer URL; enables OIDC sign-in |
| `METIS_OIDC_AUDIENCE` | | The audience tokens must carry (comma-separated for several) |
| `METIS_OIDC_JWKS_URL` | discovered | Where to fetch signing keys, when the provider's address differs inside the network |
| `METIS_OIDC_JWKS_FILE` | | Signing keys from a file, for networks without access to the provider |
| `METIS_OIDC_ROLES_CLAIM` | `roles` | Dotted path of the claim that lists roles |
| `METIS_OIDC_EMAIL_CLAIM` | `email` | The claim that names a person |
| `METIS_OIDC_NAME_CLAIM` | `name` | The claim with a person's display name |
| `METIS_OIDC_REQUIRE_EMAIL_VERIFIED` | `false` | Name people by email only when the token marks it verified |
| `METIS_OIDC_PARTICIPANT_CLAIM` | | A claim the provider uses to name the participant URI (of the token's kind); off when empty |
| `METIS_OIDC_ADMIN_ROLE` | `metis-admin` | The role (or proxy group) that grants global admin |
| `METIS_OIDC_AUDITOR_ROLE` | `metis-auditor` | The role (or proxy group) that grants global auditor |
| `METIS_API_KEYS_FILE` | | The hashed API keys file; enables API-key sign-in |
| `METIS_TRUSTED_PROXY_SECRET` | | The proxy's shared secret; enables trusted-header sign-in |
| `METIS_TRUSTED_PROXY_EMAIL_HEADER`, `METIS_TRUSTED_PROXY_GROUPS_HEADER` | `X-Forwarded-Email`, `X-Forwarded-Groups` | The headers the proxy sets |
| `METIS_ADMINS` | | People (`human:` URIs) with the global admin role |
| `METIS_CORS_ORIGINS` | | Browser origins allowed to call the API |
| `METIS_WHISPER_DEADLINE_HOURS` | `168` | How long a worker has to answer a whisper, for workspaces created through the API |
| `METIS_ESCALATION_GRANT_HOURS` | `12` | How long a person's decision on an escalated situation holds for the agent that asked |
| `METIS_USE_LIVE_MODEL` | `false` | Use the local model (Ollama) at `METIS_MODEL_URL` for drafting |
| `METIS_MODEL_URL`, `METIS_MODEL_NAME` | `http://localhost:11434`, `gemma4` | Where the local model runs, for example a Service in the cluster |
| `METIS_ENGINE_CACHE_SIZE` | `64` | Workspaces kept in memory between requests |
| `METIS_MIGRATE_ON_START` | `true` | Create or upgrade the schema on start; `false` only checks it |
| `METIS_LOCK_TIMEOUT_SECONDS` | `30` | How long a write waits for its workspace before answering 503 |
| `METIS_STATEMENT_TIMEOUT_SECONDS` | `60` | The longest a statement in a workspace write may run (PostgreSQL) |
| `METIS_DB_POOL_SIZE`, `METIS_DB_MAX_OVERFLOW` | `5`, `10` | Database connections per process (PostgreSQL) |
| `METIS_DB_APP_ROLE` | | For `metis server migrate`: the servers' own role, granted what it needs and no more (PostgreSQL) |
| `METIS_MAX_BODY_BYTES` | `4194304` | Larger request bodies get 413 |
| `METIS_API_DOCS` | `false` | Serve the interactive API reference at `/docs` |
| `METIS_PUBLIC_URL` | | The address people use; notifications link to its web app |
| `METIS_UI_CLIENT_ID` | | The public OIDC client the web app signs people in with |
| `METIS_UI_SCOPES` | `openid profile email` | The scopes the web app asks for |
| `METIS_NOTIFICATIONS_FILE` | | Notification channels; with a file, the shortcuts below are ignored |
| `METIS_SMTP_HOST`, `METIS_SMTP_PORT`, `METIS_SMTP_USERNAME`, `METIS_SMTP_PASSWORD`, `METIS_SMTP_FROM`, `METIS_SMTP_STARTTLS` | port `587`, from `metis@localhost`, STARTTLS on | An email channel |
| `METIS_NOTIFY_SLACK_WEBHOOK_URL`, `METIS_NOTIFY_TEAMS_WEBHOOK_URL` | | A Slack or Teams channel |
| `METIS_NOTIFY_WEBHOOK_URL`, `METIS_NOTIFY_WEBHOOK_SECRET`, `METIS_NOTIFY_WEBHOOK_PERSONAL` | | A signed webhook channel; `PERSONAL=true` adds events about people |
| `METIS_NOTIFY_LOG` | `false` | Log every notification |
| `METIS_SWEEP_INTERVAL_SECONDS` | `300` | How often whisper deadlines and review dates are checked; `0` turns it off |
| `METIS_DISPATCH_INTERVAL_SECONDS` | `5` | How often queued notifications are delivered; `0` turns it off |
| `METIS_OUTBOX_RETENTION_DAYS` | `30` | When delivered and failed notifications are cleared |
| `METIS_REMOTE_MCP` | `true` | Serve MCP for agents at `/mcp` |
| `METIS_CONNECTORS_FILE` | | Source mappings for ingestion; see [connectors.md](../docs/connectors.md) |
| `METIS_SLACK_BOT_TOKEN`, `METIS_SLACK_SIGNING_SECRET` | | Whispers as Slack direct messages, answered in Slack (both, or neither) |
| `METIS_TEAMS_APP_ID`, `METIS_TEAMS_APP_PASSWORD` | | Whispers as Teams cards, answered in Teams (both, or neither) |
| `METIS_TEAMS_TENANT_ID`, `METIS_TEAMS_ALLOWED_TENANTS` | | The Microsoft Entra tenants whose people may use the Teams bot; one is required |
| `METIS_TEAMS_SERVICE_HOSTS` | the Bot Framework's Teams hosts | The hosts the bot sends to, for other clouds |
| `METIS_LOG_LEVEL` | `info` | Server log level |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose forwarded client addresses the server trusts (read by uvicorn) |

## Kubernetes

```bash
docker build -t registry.example.com/metis-server:0.1.5 .
docker push registry.example.com/metis-server:0.1.5

kubectl create secret generic metis-database \
  --from-literal=database-url='postgresql://metis:password@postgres:5432/metis'
metis server api-key create --id cmms --uri agent:cmms-connector --file api-keys.yaml
kubectl create secret generic metis-api-keys --from-file=api-keys.yaml

helm install metis deploy/helm/metis \
  --set image.repository=registry.example.com/metis-server \
  --set database.existingSecret=metis-database \
  --set apiKeys.existingSecret=metis-api-keys \
  --set oidc.issuer=https://login.example.com/realms/metis \
  --set oidc.rolesClaim=realm_access.roles \
  --set 'admins={human:ana@example.com}' \
  --set replicaCount=2
```

The chart runs the container as a non-root user with a read-only root filesystem, checks
`/readyz` and `/healthz`, and refuses to render without a way to sign in, or with several
replicas and no PostgreSQL database, or SQLite without a persistent volume. The volume outlives
`helm uninstall`. With several replicas it adds a PodDisruptionBudget and spreads the pods across
nodes. `migrations.runAsJob` runs `metis server migrate` as a pre-upgrade Job with its own
database Secret, and the pods only check the schema; with `migrations.appRole`, each migration
grants the pods' role what it needs and no more. Source mappings and chat credentials go in
Secrets named by `connectors.existingSecret`, `slack.existingSecret`, and `teams.existingSecret`.
A change to a Secret you manage takes effect after `kubectl rollout restart`. The chart adds no
NetworkPolicy, because what Metis must reach (database, identity provider, SMTP, Slack, the Bot
Framework, webhooks, the local model) differs by site; add one that allows those. For a
reproducible image, pin the base image in the Dockerfile by digest. See
[`helm/metis/values.yaml`](helm/metis/values.yaml) for every value.
