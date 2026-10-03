# The Metis MCP server

`metis mcp` serves a project's governed tacit memory to any Model Context Protocol client,
such as Claude Desktop or Claude Code. An agent connected to it can ask for guidance that fits
the situation in front of it, assemble a memory context for a task, report where practice
diverged from procedure, and relay a worker's own answers. It cannot review, promote, or
authorise anything: those decisions stay with named people.

## Install and run

```bash
pip install "metis-memory[mcp]"
metis mcp
```

The server speaks MCP over stdio. It serves the active workspace of the project in
`$METIS_HOME` (default `./.metis`); choose another with `--workspace`. When the project has no
workspace yet, the server seeds the pump demo so there is governed memory to try at once;
`--no-seed-demo` turns that off. Every retrieval, capture, and contest is recorded on the
workspace's hash-linked CHAP chain and its append-only ledger, exactly as the CLI records them.

While the server runs it is the workspace's only writer. CLI commands that record something on the
same workspace (`metis retrieve`, `metis memory query`) are refused with a clear message;
inspection (`metis fragment list`, `metis audit verify`) keeps working. Use another workspace for
CLI work, or stop the server first.

## Connect a client

**Claude Code**

```bash
claude mcp add metis --env METIS_HOME=/path/to/project/.metis -- metis mcp
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "metis": {
      "command": "metis",
      "args": ["mcp"],
      "env": { "METIS_HOME": "/path/to/project/.metis" }
    }
  }
}
```

Any other MCP client works the same way: run `metis mcp` as a stdio server.

## Tools

| Tool | What it does | Changes state |
|------|--------------|---------------|
| `retrieve_guidance` | Returns tacit guidance whose recorded conditions match the context, with use constraints, and anything a person must decide. | Records the decision |
| `agent_memory_context` | Assembles procedural, semantic, episodic, and gated tacit memory for a task. | Records the query |
| `list_tacit_memory` | Lists agent-visible memory: identifiers, titles, categories, conditions, review dates. The guidance text comes only through the gate. | No |
| `describe_workspace` | Fragments by authority layer, pending whispers, reviewers, chain status. | No |
| `submit_observation` | Reports a divergence from procedure; returns one short question for the worker. | Starts a capture |
| `list_pending_whispers` | Whispers waiting for a worker's answer. | No |
| `answer_whisper` | Relays the worker's own answer and consent; stores an Evidence-layer fragment when the worker confirms or corrects it and grants consent. | Completes a capture |
| `contest_fragment` | Relays a challenge, correction, withdrawal, or re-elicitation request. | Opens a review or revokes |
| `audit_verify` | Verifies the evidence chain and checks the ledger agrees. | No |
| `audit_tail` | The latest chain entries. | No |

Two resources describe the rules: `metis://governance` (the contract below) and
`metis://taxonomy` (the K1 to K17 categories and their capture modalities).

## The contract the tools enforce

- **Guidance only through the gate.** Content reaches an agent only from `retrieve_guidance`
  and `agent_memory_context`, which apply the condition-aware gate. Listing tools return
  metadata (identifiers, titles, conditions), so the guidance text reaches an agent only
  through the gate.
- **Unauthorised fragments stay out of sight.** Evidence-layer and unreviewed fragments appear
  only as a count (`not_yet_authorised`).
- **A person decides when it matters.** High-risk situations and near misses come back as
  `required_human_actions` with an escalation task for the operator, and the agent waits for
  that person.
- **Workers speak for themselves.** `submit_observation`, `answer_whisper`, and
  `contest_fragment` require a `human:` participant URI, and only the worker a whisper was
  addressed to may answer it. Consent is stated with the answer: `granted` stores the
  fragment; `declined` records the answer and stores nothing.
- **No tool grants authority.** Promotion needs a quorum of named Mission Group reviewers,
  outside this surface. Contests open a review or revoke a fragment; promotion stays with the
  reviewers.
- **Whispers are rationed.** A worker receives at most five whispers in eight hours by
  default; beyond that, `submit_observation` defers and records the deferral.

## A worked flow

1. The agent calls `retrieve_guidance` with the live context of pump A under high load on the
   night shift. Metis returns the advisory cue with its use constraints.
2. The same call with `risk_class: "high"` withholds the guidance and returns an escalation
   task and a required human action: the agent stops and involves the operator.
3. The agent notices a new divergence and calls `submit_observation` for
   `human:operator@plant_a`. Metis returns a whisper such as "You noticed something before the
   formal measure changed. What cue made you pause?"
4. The operator answers in their own words. The client relays it with `answer_whisper`,
   `answered_by: "human:operator@plant_a"`, and the operator's consent. Metis stores the
   fragment in the Evidence layer, invisible to agents until reviewers promote it.

## Trust model

The server runs locally over stdio and trusts the identities its client supplies: it checks
their form (`human:` versus `agent:`) and relies on the client for who is speaking. That suits a
reference toolkit and a single user. A deployment that serves many people must put
authenticated identity between the client and these tools.
