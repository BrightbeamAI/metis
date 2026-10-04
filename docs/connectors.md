# Capture connectors

Connectors bring capture to the systems where work is already recorded. A maintenance system, a
production log, or a ticketing tool sends its records to Metis; each record that shows a worker
acting differently from the procedure becomes an observation, and the worker gets one short
question. Workers answer in the web app, which notification emails link to, or directly in Slack
or Microsoft Teams.

## Map a source

A mappings file (`METIS_CONNECTORS_FILE`) says, for each source, where to find what was done,
what the procedure expected, who the worker is, and the situation:

```yaml
sources:
  cmms:
    records: $.items                     # where the records sit in a pushed payload
    id: $.work_order.id                  # the source's own id; a record is captured once
    worker: $.work_order.technician      # an email, a participant URI, or an id below
    worker_map: {T-17: "human:walt@example.com"}
    work_as_done: $.work_order.action_taken
    work_as_imagined: $.work_order.procedure_step
    title: "Work order {work_order.id}"
    category: K4_equipment_specific      # optional; the inference suggests one otherwise
    when: $.work_order.deviation == true # only records that show a divergence
    context:
      equipment_family: $.asset.family
      equipment_id: $.asset.id
      site: plant_a                      # a literal
```

A value is a field (`$.a.b`, `$['Action taken']` for names with spaces, `[0]` for list items),
a template that fills fields into text (`Work order {work_order.id}`), or a literal. A filter is
a field, `not` a field, or a comparison (`==`, `!=`).

Check a mapping against a sample before connecting anything; nothing is captured:

```bash
metis connector check --source cmms --file sample.json --mappings connectors.yaml
```

## Send records

Give the source system a capture identity: an API key, or an OAuth client, with the `capture`
role in the workspace.

```bash
metis server api-key create --id cmms --uri agent:cmms-connector
metis server member set --workspace wsp_plant_a --uri agent:cmms-connector --roles capture
```

Then either push records from the source, or import files.

- **Push.** The source (or an integration platform) posts its own payload to
  `POST /v1/workspaces/{workspace}/ingest/{source}` with the API key as a bearer token: one
  record, a list, or the payload with the records where the mapping's `records` path says.
- **Import.** Export records to JSON, JSON Lines, or CSV and import them through a server. With
  the mappings file at hand (`--mappings` or `METIS_CONNECTORS_FILE`), the command sends the
  records in batches of `--batch`:

  ```bash
  metis connector import --workspace wsp_plant_a --source cmms --file orders.jsonl \
    --server https://metis.example.com --api-key "$METIS_API_KEY"
  ```

  Without `--server`, the command writes to the database in `METIS_DATABASE_URL` directly; it
  then needs the mappings file and `--as`, the capture source to record the observations as.

Either way the response counts what happened: `accepted` (each with the whisper it raised, or
`deferred` when the worker's whisper budget holds the question back), `duplicates` (records
captured before, so sending the same records again is safe), `filtered` (records the `when`
filter left out), and `failed` (with the reason, for example a worker who is not a member, or
text above the size limits). A failed record is skipped before anything is recorded for it. A
request carries up to 1000 records, committed 50 at a time; if one part fails, send the request
again, and the records committed before are reported as duplicates.

## Whispers in Slack

Create a Slack app with the bot scopes `chat:write`, `users:read`, and `users:read.email`, turn on
Interactivity with the request URL `https://<server>/integrations/slack/interactions`, and set
`METIS_SLACK_BOT_TOKEN` and `METIS_SLACK_SIGNING_SECRET`.

Each whisper then reaches the worker as a direct message from the app, with the question, the
record that prompted it, a consent box, and answer buttons; "Correct it" opens a form for their
own words. Text from the record is escaped, so it cannot add links or mentions. Metis checks
Slack's signature on every interaction, looks up the person's email in Slack (a deactivated
account has none), and records the answer only when that person is the worker the whisper asked.
Slack and Metis must agree on email addresses, so use the addresses your identity provider
issues.

## Whispers in Microsoft Teams

Register an Azure Bot with the Microsoft Teams channel and the messaging endpoint
`https://<server>/integrations/teams/messages`, publish a Teams app for it, and set
`METIS_TEAMS_APP_ID`, `METIS_TEAMS_APP_PASSWORD`, and the Microsoft Entra tenants whose people may
use it: `METIS_TEAMS_TENANT_ID` for a single-tenant bot, or `METIS_TEAMS_ALLOWED_TENANTS` for
several. The server refuses to start the bot without one.

A bot can open a personal chat only with someone who has its app installed, so install the app for
workers; a Teams admin can install it for everyone. Each installation tells Metis where to reach
that person, bound to their Entra account: another account reporting the same email is refused,
and removing the app makes Metis forget where to reach them. Each whisper then arrives as an
Adaptive Card with the question, the record, a consent toggle, and answer actions. On every
activity Metis verifies the Bot Framework's token (its signature, its expiry, and the service it
was issued for), the tenant, and the channel; it sends only to the Bot Framework's Teams service
hosts (for other clouds, `METIS_TEAMS_SERVICE_HOSTS` gives the whole list). It looks up the
person's email in Teams, records
the answer as that worker, and replaces the card with a confirmation. A whisper to someone who
has not installed the app is retried for about an hour, and the person can always answer in the
web app.

Each allowed tenant's administrators decide the email their people report to Teams, and Metis
binds an email to the first Entra account that reports it. Allow only tenants you trust with your
people's identities. To bind a person to another account (a new account, or a mistaken binding),
run `metis server forget-chat-identity --participant human:<email>`; their next installation
binds again.
