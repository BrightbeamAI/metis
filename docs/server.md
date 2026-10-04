# The Metis server

The Metis server runs governed tacit memory for many people and agents at once. It is the same
engine as the toolkit, with five additions around it:

- **Identity from sign-in.** A request acts as the identity its credentials prove: an OIDC
  access token, an API key, or a trusted proxy's headers. No request names the identity it acts
  as.
- **Roles per workspace.** Each workspace's members hold roles, and the roles decide what each
  member may do. Every change to a member's roles is recorded on the workspace's CHAP chain.
- **One vote per reviewer.** Each Mission Group reviewer records their own decision, and a
  promotion completes when the approvals meet the review rule.
- **Transactions.** A request commits everything it recorded (domain state, CHAP chain, evidence
  ledger) together, or nothing, and each workspace has one writer at a time.
- **Deployment.** PostgreSQL or SQLite storage, a container image, Docker Compose, and a Helm
  chart. See [deploy/README.md](../deploy/README.md).

Install it with `pip install "metis-memory[server,postgres]"` and start it with
`metis server run`. The interactive API reference is at `/docs` on a running server.

## Roles

| Role | Who holds it | What it allows |
| --- | --- | --- |
| `worker` | people | answer whispers addressed to them; report their own observations; read, contest, and withdraw the fragments they contributed |
| `reviewer` | people | vote on reviews, open reviews, retire fragments, contest fragments, read every fragment |
| `agent` | agents | receive governed guidance and assembled memory; list visible memory |
| `capture` | agents, services, or people | report observations for any worker in the workspace |
| `escalation` | people | see the retrievals the gate hands to a person |
| `auditor` | people or services | read fragments and the evidence chain, verify it, and export it |
| `admin` | people | manage the workspace's members |

Two roles hold across workspaces and come from sign-in: the global `admin` creates workspaces
and manages any workspace's members, and the global `auditor` reads every workspace. A global
role grants no workspace role, so an administrator who reviews fragments is also a reviewer
member of that workspace. The Mission Group is the set of members with the reviewer role.

## Signing in

| Method | Configure | The identity Metis records |
| --- | --- | --- |
| OIDC access token | `METIS_OIDC_ISSUER`, `METIS_OIDC_AUDIENCE` | `human:<email>` for a person; `agent:<client id>` for a client signing in with its own credentials |
| API key | `METIS_API_KEYS_FILE` | the participant URI the key was issued for |
| Trusted proxy | `METIS_TRUSTED_PROXY_SECRET` | `human:<email>` from the proxy's `X-Forwarded-Email` header |

Send a token or key as `Authorization: Bearer <token>`; an API key may also go in `X-API-Key`.
An identity provider may set the participant URI outright in the `metis_participant` claim. The
roles claim (`METIS_OIDC_ROLES_CLAIM`) grants the global roles named by
`METIS_OIDC_ADMIN_ROLE` and `METIS_OIDC_AUDITOR_ROLE`.

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
   connector's.

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
   a person. The decision is recorded under the agent's identity.

   ```http
   POST /v1/workspaces/wsp_plant_a/retrieve
   {"context": {"equipment_family": "centrifugal_pump", "operating_mode": "high_load"}}
   ```

6. **An auditor verifies the chain.** `GET /v1/workspaces/wsp_plant_a/audit/verify` replays the
   hash-linked chain and compares it with the evidence ledger, entry for entry.

## API

| Method and path | Who may call it |
| --- | --- |
| `GET /healthz`, `GET /readyz` | anyone |
| `GET /v1/me` | anyone signed in |
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
| `GET /v1/workspaces/{id}/audit`, `.../audit/verify`, `.../audit/export` | auditor, admin |

Responses use standard status codes: 401 without valid credentials, 403 when the caller's roles
do not allow the action, 404 for something that does not exist (or that the caller may not
know exists), 409 when the action conflicts with a fragment's state or an open review, and 422
for invalid input.

## Storage and consistency

The SQL repository keeps four tables: `metis_workspaces` (each workspace's domain state and a
version counter), `chap_workspaces` (the CHAP snapshot, in CHAP's own store schema),
`metis_evidence_ledger` (one row per evidence entry, append-only, enforced by database
triggers), and `metis_schema`.

A write runs inside one transaction. Within a process, a lock serialises each workspace's
writers; across processes, a PostgreSQL advisory lock does; and a version check on save refuses
a stale writer, which is retried on fresh state. The CHAP snapshot is taken once per
transaction. A failed request rolls back everything it recorded, and the next request starts
from the committed state. A read records nothing.

Each write stores the workspace's full CHAP snapshot, so its cost grows with the chain. Give
each site, line, or team its own workspace.

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
