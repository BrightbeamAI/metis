# Connecting agents to the Metis server

An agent receives governed tacit memory from the Metis server: guidance only where its recorded
conditions match the situation, with the use constraints that travel with it, and a person's
decision whenever the gate asks for one. Every retrieval is recorded on the workspace's CHAP
chain under the agent's own identity.

| Your agent | Connect through |
| --- | --- |
| Claude Code, the Claude Agent SDK, the OpenAI Agents SDK, LangGraph, or any MCP client | the remote MCP endpoint, `https://<server>/mcp` |
| Your own Python code | `metis.client.MetisClient` or `AsyncMetisClient` |
| A model API that calls functions (OpenAI, Anthropic) | `metis.integrations.agent_tools.MetisToolbox` |
| A LangChain chain or agent | `metis.integrations.langchain` |

For an agent on the same machine as a local project, `metis mcp` serves the same tools over
stdio; see [mcp_server.md](mcp_server.md).

## Give the agent an identity

1. **Credentials.** Either issue an API key (`metis server api-key create --id assistant --uri
   agent:shift-assistant`) or register the agent as a client in your identity provider. A client
   that signs in with its own credentials becomes `agent:<client id>`.
2. **Membership.** A workspace admin adds the agent with the `agent` role. Give the `capture` role
   to agents that report observations of work.

```bash
metis server member set --workspace wsp_plant_a --uri agent:shift-assistant --roles agent
```

## The contract an agent keeps

- Ask for guidance with the current situation, and give every field you know: an unknown value
  does not count as a match. Always give the situation's `risk_class` (`low`, `moderate`, `high`,
  or `critical`); a request without one is refused, because high-risk situations go to a person.
- Treat guidance as situated advice for those conditions, and honour every use constraint.
- When `required_human_actions` lists anything, stop. A person decides, and `check_escalation`
  (or `MetisClient.wait_for_escalation`) reports the decision: `applies`, `does_not_apply`, or
  `refer_to_review`. After `applies`, the same agent asking again with the same context within
  the decision's window (12 hours by default) receives the guidance, recorded as given on that
  person's decision. Asking again before anyone decides reuses the same escalation, so a person
  is asked once.
- Leave workers' answers and reviewers' votes to people. Workers answer whispers and reviewers vote
  in the web app; no agent tool does either.

## Remote MCP

The server answers MCP over streamable HTTP at `/mcp` (POST, with JSON responses). Send the
agent's API key or access token as a bearer token on every request; the endpoint is stateless, so
any replica serves any request. A refusal (a missing role, a workspace the agent does not belong
to, invalid input) comes back as a tool error with its reason. Every tool publishes a JSON Schema
for its arguments and its result, with each field described, and declares the MCP behaviour
hints; `submit_observation` is safe to retry with the same observation id.

| Tool | Role | What it does |
| --- | --- | --- |
| `list_workspaces` | any | the agent's workspaces and its roles in each |
| `describe_workspace` | member | review rule, reviewers, visible memory, chain status |
| `retrieve_guidance` | agent | governed guidance for a situation, recorded under the agent's identity |
| `agent_memory_context` | agent | procedural, semantic, episodic, and gated tacit memory for a task |
| `list_tacit_memory` | agent | metadata of the memory the agent can receive |
| `check_escalation` | agent | an escalation the agent raised, and the person's decision |
| `submit_observation` | capture | report where a worker's action differed from the procedure |

Claude Code:

```bash
claude mcp add --transport http metis https://metis.example.com/mcp \
  --header "Authorization: Bearer $METIS_API_KEY"
```

The OpenAI Agents SDK:

```python
from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp

async with MCPServerStreamableHttp(params={
        "url": "https://metis.example.com/mcp",
        "headers": {"Authorization": f"Bearer {api_key}"}}) as metis:
    agent = Agent(name="Shift assistant", mcp_servers=[metis],
                  instructions="Ask Metis for guidance before acting on equipment.")
    result = await Runner.run(agent, "Pump A is loud under high load. What should I do?")
```

The Claude Agent SDK:

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(mcp_servers={"metis": {
    "type": "http", "url": "https://metis.example.com/mcp",
    "headers": {"Authorization": f"Bearer {api_key}"}}})
```

LangGraph, with `langchain-mcp-adapters`:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({"metis": {
    "transport": "streamable_http", "url": "https://metis.example.com/mcp",
    "headers": {"Authorization": f"Bearer {api_key}"}}})
tools = await client.get_tools()
```

## The Python client

```python
from metis.client import ClientCredentials, MetisClient

client = MetisClient("https://metis.example.com", credentials=ClientCredentials(
    "https://login.example.com/realms/metis/protocol/openid-connect/token",
    client_id="shift-assistant", client_secret=secret))

situation = {"equipment_family": "centrifugal_pump", "operating_mode": "high_load",
             "risk_class": "moderate"}
result = client.retrieve("wsp_plant_a", situation)
if result["required_human_actions"]:
    decision = client.wait_for_escalation("wsp_plant_a", result["escalation_task_id"])
for item in result["guidance"]:
    print(item["guidance"], item["use_constraints"])
```

`api_key=` and `token=` (a string, or a function that returns a fresh token) sign in too. With
`ClientCredentials`, a token the server rejects is replaced once, and the request sent again.
Errors raise `NotAuthenticated`, `Forbidden`, `NotFound`, `Conflict`, or `Invalid`, each carrying
the server's reason. `AsyncMetisClient` has the same methods as coroutines. The client also covers
capture sources (`observe`), workers (`answer_whisper`, `contest`, `withdraw`), reviewers
(`reviews`, `vote`), escalation handlers (`decide_escalation`), and auditors (`audit_verify`).

## Function tools for model APIs

```python
import anthropic
from metis.integrations.agent_tools import MetisToolbox

toolbox = MetisToolbox(client, workspace="wsp_plant_a")
response = anthropic.Anthropic().messages.create(
    model=model, max_tokens=1024, tools=toolbox.anthropic_tools(), messages=messages)
for block in response.content:
    if block.type == "tool_use":
        result = toolbox.call(block.name, block.input)  # send back as a tool_result
```

`openai_tools()` and `openai_responses_tools()` give the same tools for the OpenAI Chat
Completions and Responses APIs. A refusal or a bad argument comes back from `call` as
`{"error": ..., "status": ...}` for the model to read, so it ends no agent run.

## LangChain

```python
from metis.integrations.langchain import MetisRetriever, metis_tools

tools = metis_tools(client, "wsp_plant_a")
retriever = MetisRetriever(client=client, workspace="wsp_plant_a",
                           context_provider=lambda: current_situation())
```

The retriever returns one document per piece of guidance, with its use constraints in the
metadata. When a person must decide first, it returns documents of type `required_human_action`
in their place.
