# The Metis server

The Metis server runs governed tacit memory for many people and agents at once. It is the same
engine as the toolkit, with these additions around it:

- **Identity from sign-in.** A request acts as the identity its credentials prove: an OIDC
  access token, an API key, or a trusted proxy's headers. No request names the identity it acts
  as.
- **Roles per workspace.** Each workspace's members hold roles, and the roles decide what each
  member may do. Every change to a member's roles is recorded on the workspace's CHAP chain.
- **One vote per reviewer.** Each Mission Group reviewer records their own decision, and a
  promotion completes when the approvals meet the review rule.
- **Transactions.** A request commits everything it recorded (domain state, CHAP chain, evidence
  ledger) together, or nothing, and each workspace has one writer at a time.
- **People's workflows.** An inbox and web app for workers, reviewers, and escalation handlers;
  decisions on escalated retrievals; whisper deadlines; and notifications by email, Slack,
  Teams, or webhook.
- **Connectors.** Records from workplace systems become observations, and workers can answer
  whispers in Slack or Microsoft Teams. See [connectors.md](connectors.md).
- **Deployment.** PostgreSQL or SQLite storage, a container image, Docker Compose, and a Helm
  chart. See [deploy/README.md](../deploy/README.md).

Install it with `pip install "metis-memory[server,postgres]"` and start it with
`metis server run`. Set `METIS_API_DOCS=true` for the interactive API reference at `/docs`; the
schema is always at `/openapi.json`. A pip install carries no `prompts/` directory, so whispers
use the generic wording unless `METIS_REPO` names a checkout of the repository (the container
image includes the prompts). Running it in production: [operations.md](operations.md).

## Roles

| Role | Who holds it | What it allows |
| --- | --- | --- |
| `worker` | people | answer whispers addressed to them; report their own observations; read, contest, and withdraw the fragments they contributed |
| `reviewer` | people | vote on reviews, open reviews, retire fragments, contest fragments, read every fragment |
| `agent` | agents | receive governed guidance and assembled memory; list visible memory |
| `capture` | agents, services, or people | report observations for any worker in the workspace |
| `escalation` | people | see and decide the retrievals the gate hands to a person |
| `auditor` | people or services | read fragments and the evidence chain, verify it, and export it |
| `admin` | people | manage the workspace's members |

Two roles hold across workspaces and come from sign-in: the global `admin` (people only) creates
workspaces and manages any workspace's members, and the global `auditor` (people and services)
reads every workspace. A third, `metrics`, reads only the server's counts, for monitoring. A global role grants no workspace role, so an administrator who reviews
fragments is also a reviewer member of that workspace. The Mission Group is the set of members
with the reviewer role. A reviewer never decides on a fragment they contributed, and an
approval counts only while its reviewer is a member: when a reviewer leaves, the open reviews
that counted on them start again for the remaining reviewers.

A workspace someone has never belonged to looks to them exactly like one that does not exist (404).
A former member's requests still reach it, where their roles (now none) decide, so a worker who
left can still withdraw consent for what they contributed.

## Signing in

| Method | Configure | The identity Metis records |
| --- | --- | --- |
| OIDC access token | `METIS_OIDC_ISSUER`, `METIS_OIDC_AUDIENCE` | `human:<email>` for a person; `agent:<client id>` for a client signing in with its own credentials |
| API key | `METIS_API_KEYS_FILE` | the participant URI the key was issued for |
| Trusted proxy | `METIS_TRUSTED_PROXY_SECRET` | `human:<email>` from the proxy's `X-Forwarded-Email` header |

Send a token or key as `Authorization: Bearer <token>`; an API key may also go in `X-API-Key`.
A request that carries a credential twice is refused. A token whose `email_verified` is false
names the person by subject (`human:<subject>@<issuer host>`); with
`METIS_OIDC_REQUIRE_EMAIL_VERIFIED=true`, so does a token that does not say. With
`METIS_OIDC_PARTICIPANT_CLAIM` set, a provider may name the participant URI in that claim, of the
same kind as the token (a person's token names a `human:`, a client's an `agent:` or `service:`).
The roles claim (`METIS_OIDC_ROLES_CLAIM`) grants the global roles named by
`METIS_OIDC_ADMIN_ROLE` and `METIS_OIDC_AUDITOR_ROLE`. If the provider's keys cannot be fetched,
OIDC sign-in answers 503 and API keys keep working.

## One fragment through the server

The calls below follow the pump example. Each runs as the identity its token proves.

1. **A global admin creates the workspace and names its members.**

   ```http
   POST /v1/workspaces
   {"id": "wsp_plant_a", "name": "Plant A", "site": "plant_a", "members": [
     {"uri": "human:wendy@example.com", "roles": ["worker"]},
     {"uri": "human:rhea@example.com", "roles": ["reviewer"]},
     {"uri": "human:raj@example.com", "roles": ["reviewer", "escalation"]},
     {"uri": "agent:shift-assistant", "roles": ["agent"]},
     {"uri": "agent:cmms-connector", "roles": ["capture"]}]}
   ```

2. **A capture source reports an observation for a worker.** Metis infers a candidate (a
   hypothesis only) and asks the worker one whisper. The observation is recorded as the
   connector's. Reporting the same observation again returns the same whisper, so a source can
   retry safely; another observation under a recorded id is refused (409).

   ```http
   POST /v1/workspaces/wsp_plant_a/observations
   {"observation_id": "WO-4471", "worker": "human:wendy@example.com", "category": "K7_sensory",
    "work_as_done": "Eased back earlier, when high load met a dull sound.",
    "context": {"equipment_family": "centrifugal_pump", "operating_mode": "high_load"}}
   ```

3. **The worker answers in their own words.** `GET /v1/workspaces/wsp_plant_a/whispers` lists the
   whispers addressed to the caller. Only the worker asked may answer, and the fragment is stored
   in the Evidence layer only when they confirm or correct it and grant consent.

   ```http
   POST /v1/workspaces/wsp_plant_a/whispers/{whisper_id}/answer
   {"response": "confirm", "consent": "granted"}
   ```

4. **Reviewers vote.** `GET /v1/workspaces/wsp_plant_a/reviews` is the Mission Group's queue:
   fragments awaiting a first review, with an open review, or past their review date. The first
   approval proposes the promotion, with the use constraints that travel with the fragment; each
   later approval approves that proposal. The promotion is applied when the approvals meet the
   review rule (`quorum:2` by default). One reviewer can hold, reject, or send the fragment back
   for re-elicitation, which decides the review at once.

   ```http
   POST /v1/workspaces/wsp_plant_a/fragments/TF-00001/votes
   {"outcome": "promoted_to_advisory", "summary": "Clear, recurring cue.",
    "use_constraints": ["Present as an advisory cue only."]}
   ```

5. **An agent asks for guidance.** The gate returns the fragment only where its recorded
   conditions match, with its use constraints, and hands high-risk situations and near misses to
   a person. The context must name its `risk_class` (`low`, `moderate`, `high`, or `critical`).
   The decision is recorded under the agent's identity.

   ```http
   POST /v1/workspaces/wsp_plant_a/retrieve
   {"context": {"equipment_family": "centrifugal_pump", "operating_mode": "high_load",
                "risk_class": "moderate"}}
   ```

6. **A person decides an escalation.** A high-risk situation, or a near miss, opens an escalation;
   the agent asking again in the same situation gets the same escalation. A member with the
   escalation role records whether the guidance `applies`, `does_not_apply`, or needs the
   reviewers (`refer_to_review`); the agent reads the decision from
   `GET /v1/workspaces/wsp_plant_a/escalations/{task_id}`. The decision holds for that agent and
   that exact situation for `METIS_ESCALATION_GRANT_HOURS` (12 by default): asking again then
   returns the guidance a person said applies, and the retrieval records whose decision it was;
   guidance a person said does not apply stays withheld without asking again.

   ```http
   POST /v1/workspaces/wsp_plant_a/escalations/{task_id}/decision
   {"outcome": "does_not_apply", "rationale": "High risk: follow SOP-17 strictly."}
   ```

7. **An auditor verifies the chain.** `GET /v1/workspaces/wsp_plant_a/audit/verify` replays the
   hash-linked chain and compares it with the evidence ledger, entry for entry.

## The web app

People work in the web app at `/app`. Each person sees the sections their roles call for:

- **Whispers:** the questions about their own work, with the record that prompted each one. They
  confirm or correct the account in their own words, grant or decline consent, defer, or dismiss.
- **Reviews:** fragments awaiting their vote, with the content, conditions, evidence, and any
  proposal under review.
- **Escalations:** situations an agent's guidance needs a person to decide.
- **My contributions:** the fragments they contributed and where each stands, with challenge and
  withdraw.

The app signs people in through your identity provider with the authorization code flow and PKCE.
Register a public client whose redirect URI is `<public URL>/app`, give its tokens the API
audience, and set `METIS_UI_CLIENT_ID`. Behind a trusted proxy the app uses the proxy's sign-in;
with API keys configured it also accepts a key, for development.

## Whisper deadlines

A whisper stays open for the workspace's deadline (`METIS_WHISPER_DEADLINE_HOURS`, a week by
default). The server's sweep (every `METIS_SWEEP_INTERVAL_SECONDS`) lapses a whisper left
unanswered past it: CHAP records the lapse, Metis records a `whisper_lapsed` validation event, and
nothing is stored. `metis server sweep` runs the same pass from a scheduler.

## Notifications

People and systems hear about what concerns them. Each notification is planned inside the
transaction that recorded the change, kept in an outbox, and delivered in the background, with
retries; `metis server outbox list` shows them.

| Event | Who hears |
| --- | --- |
| `whisper.asked` | the worker asked |
| `whisper.lapsed` | the capture source that reported the observation (through a webhook with `include_personal`) |
| `review.requested`, `review.approval` | the reviewers whose vote is outstanding |
| `review.decided` | the contributing worker and the reviewers |
| `escalation.opened` | members with the escalation role |
| `escalation.decided` | the agent that asked, and the other escalation handlers |
| `fragment.contested`, `fragment.revoked` | the reviewers and the contributing worker |
| `fragment.review_due` | the reviewers, once per review date |
| `member.changed` | the member whose roles changed |

Channels:

- **Email** sends one message per person and may include that person's own content, such as the
  question a whisper asks them.
- **Slack** and **Microsoft Teams** post to a shared channel, so they carry only events with no
  one's personal content.
- **Webhooks** receive the events that carry no one's personal content, as JSON; with
  `include_personal: true` (or `METIS_NOTIFY_WEBHOOK_PERSONAL=true`) they also receive
  `whisper.asked`, `whisper.lapsed`, and `member.changed`, and each event's recipients. With a
  secret, `X-Metis-Signature` is `sha256=` followed by the HMAC-SHA256 of
  `<X-Metis-Timestamp>.<body>`: recompute it, refuse timestamps more than a few minutes old, and
  ignore an `X-Metis-Delivery` id you have seen, because a delivery may arrive twice.

Text from records and people is escaped for each channel, so it cannot add links or mentions. A
failed delivery is retried with growing delays and then marked failed; `metis server outbox
retry` sends failed notifications again. Error messages name the status and host, never a full
URL, since webhook URLs carry secrets.

Configure channels with `METIS_SMTP_HOST` (and `METIS_SMTP_PORT`, `METIS_SMTP_USERNAME`,
`METIS_SMTP_PASSWORD`, `METIS_SMTP_FROM`, `METIS_SMTP_STARTTLS`), `METIS_NOTIFY_SLACK_WEBHOOK_URL`,
`METIS_NOTIFY_TEAMS_WEBHOOK_URL`, or `METIS_NOTIFY_WEBHOOK_URL` with
`METIS_NOTIFY_WEBHOOK_SECRET`. For several channels, or to limit a channel to some events or
workspaces, name a file in `METIS_NOTIFICATIONS_FILE`; the file then lists every channel, and the
variables above are ignored:

```yaml
public_url: https://metis.example.com
channels:
  - name: email
    type: email
    smtp: {host: smtp.example.com, port: 587, username: metis,
           password_env: METIS_SMTP_PASSWORD, from: metis@example.com}
  - name: plant-a-quality
    type: teams
    webhook_url_env: PLANT_A_TEAMS_WEBHOOK
    workspaces: [wsp_plant_a]
  - name: integrations
    type: webhook
    url: https://hooks.example.com/metis
    secret_env: METIS_WEBHOOK_SECRET
    events: [review.decided, escalation.opened, escalation.decided]
```

## API

| Method and path | Who may call it |
| --- | --- |
| `GET /healthz`, `GET /readyz` | anyone |
| `GET /v1/admin/status`, `GET /metrics` | global `metrics` or auditor: counts for operators; see [operations.md](operations.md#monitoring) |
| `GET /v1/me` | anyone signed in |
| `GET /v1/me/inbox` | anyone signed in: their whispers, reviews, escalations, and contributions |
| `GET /app` | the web app; it signs people in itself |
| `GET /v1/workspaces` | anyone signed in: their workspaces, or every workspace for a global auditor or admin |
| `POST /v1/workspaces` | global admin |
| `GET /v1/workspaces/{id}` | members, global auditor |
| `GET /v1/workspaces/{id}/members` | admin, reviewer, auditor |
| `PUT /v1/workspaces/{id}/members` | admin, global admin |
| `POST /v1/workspaces/{id}/observations` | capture, or a worker for their own work |
| `GET /v1/workspaces/{id}/whispers` | worker (their own), capture (theirs), admin, auditor |
| `POST /v1/workspaces/{id}/whispers/{whisper}/answer` | the worker asked |
| `GET /v1/workspaces/{id}/fragments`, `.../fragments/{fragment}` | reviewer, auditor, admin; a worker for their own |
| `POST .../fragments/{fragment}/contest` | reviewer, or the contributing worker |
| `POST .../fragments/{fragment}/withdraw` | the contributing worker |
| `POST .../fragments/{fragment}/retire` | reviewer |
| `POST .../fragments/{fragment}/reviews` | reviewer |
| `POST .../fragments/{fragment}/votes` | reviewer |
| `GET /v1/workspaces/{id}/reviews` | reviewer, admin, auditor |
| `POST /v1/workspaces/{id}/retrieve`, `.../agent-context` | agent |
| `GET /v1/workspaces/{id}/memory` | agent, reviewer, auditor, admin |
| `GET /v1/workspaces/{id}/escalations` | escalation, reviewer, auditor, admin |
| `GET /v1/workspaces/{id}/escalations/{task}` | escalation, reviewer, auditor, admin; the agent that asked |
| `POST /v1/workspaces/{id}/escalations/{task}/decision` | escalation |
| `GET /v1/workspaces/{id}/audit`, `.../audit/verify`, `.../audit/export` | auditor, admin |
| `POST /mcp` | MCP over streamable HTTP, for agents and capture sources; see [agent_integrations.md](agent_integrations.md) |
| `GET /v1/connectors` | anyone signed in: the configured sources |
| `POST /v1/workspaces/{id}/ingest/{source}` | capture; see [connectors.md](connectors.md) |
| `POST /integrations/slack/interactions`, `POST /integrations/teams/messages` | Slack and the Bot Framework, which sign their requests |

Responses use standard status codes: 401 without valid credentials, 403 when the caller's roles
do not allow the action, 404 for something that does not exist (or that the caller may not
know exists), 409 when the action conflicts with a fragment's state or an open review, 413 for a
request body above `METIS_MAX_BODY_BYTES`, 415 for a change sent without a JSON body and without
an `Authorization` or `X-API-Key` header (a cross-site form can send neither), 422 for invalid
input, and 503 with
`Retry-After` when the workspace stays busy past `METIS_LOCK_TIMEOUT_SECONDS` or the identity
provider is unreachable. An API route's 5xx response carries a `request_id` that matches the
server's log.

Every text field has a size limit: ids 128 characters, names and titles 200, notes and reasons
2000, accounts and corrections 4000, and a context 4 KB as JSON with values of up to 256
characters. Whatever Metis accepts is recorded for good, so the HTTP API, remote MCP, and the
connectors apply the same limits.

## Storage and consistency

The SQL repository keeps these tables: `metis_workspaces` (each workspace's domain state, a
version counter, and a token unique to each commit), `chap_workspaces` (the CHAP snapshot, in
CHAP's own store schema), `metis_evidence_ledger` (one row per evidence entry, append-only,
enforced by database triggers), `metis_members` (who belongs, or once belonged, to each
workspace), `metis_outbox` (notifications awaiting delivery), `metis_chat_identities` (where to
reach people in Teams), and `metis_schema` (the schema version and the oldest that can use it).

A write runs inside one transaction. Within a process, a lock serialises each workspace's
writers; across processes, a PostgreSQL advisory lock does; and a version check on save refuses
a stale writer, which is retried on fresh state. The CHAP snapshot is taken once per
transaction, and a write that changed nothing commits nothing. A failed request rolls back
everything it recorded, and the next request starts from the committed state. A read records
nothing, and sees one consistent snapshot of the database. A server rebuilds a workspace it has
cached whenever the stored commit token differs. A rebuilt workspace's chain is verified, and
its ledger must hold as many entries as the chain, ending with the same entry;
`.../audit/verify` compares every entry.

Each write stores the workspace's full CHAP snapshot, so its cost grows with the chain. Give
each site, line, or team its own workspace.

## Agents

Agents connect through the remote MCP endpoint at `/mcp`, the Python client
(`metis.client.MetisClient`), function tools for model APIs, or LangChain. The
[agent integrations guide](agent_integrations.md) covers each. Remote MCP is on whenever the MCP
SDK is installed (it is in the `server` extra); `METIS_REMOTE_MCP=false` turns it off.

## Building on the parts

The server is assembled from parts you can replace:

- **Sign-in:** anything with `authenticate(headers) -> Principal | None` (see
  `metis.identity.Authenticator`). `AuthenticatorChain` combines several.
- **Storage:** anything that implements `metis.storage.repository.WorkspaceRepository`;
  `metis.storage.sql.SqlRepository` is the reference implementation.
- **Roles and the engine:** `MetisEngine.set_member`, `cast_review_vote`, and
  `retrieve(..., requester=...)` are the calls the server makes, so an application can embed the
  same governance without the HTTP layer.

```python
from metis.identity import ApiKeyAuthenticator, AuthenticatorChain
from metis.server import ServerSettings, create_app
from metis.storage.sql import SqlRepository

app = create_app(
    ServerSettings(),
    repository=SqlRepository("postgresql://metis:password@db/metis"),
    authenticator=AuthenticatorChain([ApiKeyAuthenticator.from_file("api-keys.yaml")]),
)
```
