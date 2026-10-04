"""Agents on the server: remote MCP, the Python client, and framework adapters."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from metis.client import (
    AsyncMetisClient,
    ClientCredentials,
    Conflict,
    EscalationTimeout,
    Forbidden,
    MetisClient,
    NotAuthenticated,
    NotFound,
)
from metis.identity import ApiKeyAuthenticator, ApiKeyEntry, AuthenticatorChain
from metis.integrations.agent_tools import MetisToolbox
from metis.server.app import create_app
from metis.server.settings import ServerSettings
from metis.storage.sql import SqlRepository

WS = "wsp_plant_a"
PEOPLE = {"admin": "human:admin@example.com", "wendy": "human:wendy@example.com",
          "rhea": "human:rhea@example.com", "raj": "human:raj@example.com",
          "agent": "agent:shift-assistant", "cmms": "agent:cmms-connector",
          "stranger": "agent:other-assistant"}
PUMP = {"equipment_family": "centrifugal_pump", "operating_mode": "high_load"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture()
def server(tmp_path):
    keys, entries = {}, []
    for name, uri in PEOPLE.items():
        key, digest = ApiKeyAuthenticator.generate()
        keys[name] = key
        entries.append(ApiKeyEntry(id=name, sha256=digest, uri=uri,
                                   global_roles=("admin",) if name == "admin" else ()))
    repo = SqlRepository(f"sqlite:///{tmp_path / 'a.db'}")
    app = create_app(ServerSettings(sweep_interval_seconds=0, dispatch_interval_seconds=0),
                     repository=repo, authenticator=AuthenticatorChain([ApiKeyAuthenticator(entries)]))
    with TestClient(app) as http:
        clients = {name: MetisClient("http://testserver", api_key=key, http=http)
                   for name, key in keys.items()}
        clients["admin"].create_workspace(WS, "Plant A", members=[
            {"uri": PEOPLE["wendy"], "roles": ["worker"]},
            {"uri": PEOPLE["rhea"], "roles": ["reviewer"]},
            {"uri": PEOPLE["raj"], "roles": ["reviewer", "escalation"]},
            {"uri": PEOPLE["agent"], "roles": ["agent"]},
            {"uri": PEOPLE["cmms"], "roles": ["capture"]}])
        yield http, clients, keys, app
    repo.close()


def _promoted(clients) -> str:
    whisper = clients["cmms"].observe(WS, "WO-1", "Eased back earlier on a dull sound.", PUMP,
                                      worker=PEOPLE["wendy"], category="K7_sensory")
    stored = clients["wendy"].answer_whisper(WS, whisper["whisper_id"], "confirm", "granted")
    fid = stored["fragment"]["fragment_id"]
    clients["rhea"].vote(WS, fid, "promoted_to_advisory", use_constraints=["Advisory only."])
    clients["raj"].vote(WS, fid, "promoted_to_advisory")
    return fid


def _mcp(http, key, method, params=None, rid=1):
    headers = {**MCP_HEADERS, **({"Authorization": f"Bearer {key}"} if key else {})}
    return http.post("/mcp", headers=headers,
                     json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def _tool(http, key, name, **arguments):
    body = _mcp(http, key, "tools/call", {"name": name, "arguments": arguments}).json()
    result = body["result"]
    payload = result.get("structuredContent")
    if payload is not None and set(payload) == {"result"}:
        payload = payload["result"]
    return result.get("isError", False), payload if payload is not None else result["content"][0]["text"]


def test_remote_mcp_serves_agents_under_their_own_identity(server):
    http, clients, keys, app = server
    assert _mcp(http, None, "tools/list").status_code == 401
    names = [t["name"] for t in _mcp(http, keys["agent"], "tools/list").json()["result"]["tools"]]
    assert {"retrieve_guidance", "check_escalation", "submit_observation"} <= set(names)
    assert not {"answer_whisper", "review", "promote"} & set(names)

    fid = _promoted(clients)
    failed, workspaces = _tool(http, keys["agent"], "list_workspaces")
    assert not failed and workspaces[0]["your_roles"] == ["agent"]
    failed, guidance = _tool(http, keys["agent"], "retrieve_guidance", workspace=WS, context=PUMP)
    assert not failed and [g["fragment_id"] for g in guidance["guidance"]] == [fid]
    assert guidance["guidance"][0]["use_constraints"] == ["Advisory only."]

    failed, message = _tool(http, keys["stranger"], "retrieve_guidance", workspace=WS, context=PUMP)
    assert failed and "needs the agent role" in str(message)
    failed, _ = _tool(http, keys["wendy"], "retrieve_guidance", workspace=WS, context=PUMP)
    assert failed

    failed, risky = _tool(http, keys["agent"], "retrieve_guidance", workspace=WS,
                          context={**PUMP, "risk_class": "high"})
    task = risky["escalation_task_id"]
    failed, status = _tool(http, keys["agent"], "check_escalation", workspace=WS, task_id=task)
    assert not failed and status["decision"] is None
    clients["raj"].decide_escalation(WS, task, "does_not_apply", "High risk: follow the SOP.")
    failed, status = _tool(http, keys["agent"], "check_escalation", workspace=WS, task_id=task)
    assert status["decision"]["outcome"] == "does_not_apply"

    failed, whisper = _tool(http, keys["cmms"], "submit_observation", workspace=WS,
                            observation_id="WO-2", work_as_done="Opened the vent first.",
                            context=PUMP, worker=PEOPLE["wendy"])
    assert not failed and whisper["worker"] == PEOPLE["wendy"]
    assert whisper["submitted_by"] == PEOPLE["cmms"]
    resources = _mcp(http, keys["agent"], "resources/list").json()["result"]["resources"]
    assert {r["uri"] for r in resources} >= {"metis://governance", "metis://taxonomy"}


def test_the_client_maps_errors_and_waits_for_decisions(server):
    http, clients, keys, app = server
    fid = _promoted(clients)
    assert clients["agent"].me()["uri"] == PEOPLE["agent"]
    assert [m["fragment_id"] for m in clients["agent"].memory(WS)] == [fid]
    with pytest.raises(Forbidden):
        clients["agent"].vote(WS, fid, "held", summary="no")
    with pytest.raises(NotFound):
        clients["rhea"].fragment(WS, "TF-99999")
    with pytest.raises(Conflict):
        clients["rhea"].request_review(WS, fid)
        clients["rhea"].vote(WS, fid, "promoted_to_advisory")
        clients["rhea"].vote(WS, fid, "promoted_to_advisory")
    with pytest.raises(NotAuthenticated):
        MetisClient("http://testserver", api_key="metis_unknown", http=http).me()

    task = clients["agent"].retrieve(WS, {**PUMP, "risk_class": "high"})["escalation_task_id"]
    with pytest.raises(EscalationTimeout):
        clients["agent"].wait_for_escalation(WS, task, timeout=0.05, interval=0.01)
    clients["raj"].decide_escalation(WS, task, "applies", "Low flow tonight; safe to ease back.")
    decision = clients["agent"].wait_for_escalation(WS, task, timeout=1, interval=0.01)
    assert decision["outcome"] == "applies"
    assert clients["admin"].audit_verify(WS)["verified"]


def test_the_async_client(server):
    http, clients, keys, app = server
    fid = _promoted(clients)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as raw:
            client = AsyncMetisClient("http://testserver", api_key=keys["agent"], http=raw)
            result = await client.retrieve(WS, PUMP)
            context = await client.agent_context(WS, "tsk_shift", PUMP)
            return result, context

    result, context = asyncio.run(run())
    assert [g["fragment_id"] for g in result["guidance"]] == [fid]
    assert [t["fragment_id"] for t in context["tacit"]] == [fid]


def test_client_credentials_are_fetched_once_and_renewed():
    calls = []

    def handler(request):
        calls.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": f"token-{len(calls)}", "expires_in": 3600})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    creds = ClientCredentials("https://idp.example.com/token", "shift-assistant", "s3cret",
                              audience="metis-api", http=http)
    assert creds.token() == "token-1" and creds.token() == "token-1"
    assert calls[0]["grant_type"] == "client_credentials" and calls[0]["audience"] == "metis-api"
    creds._expires = 0  # expired
    assert creds.token() == "token-2"


class FakeClient:
    def __init__(self):
        self.calls = []

    def retrieve(self, workspace, context, role=None):
        self.calls.append(("retrieve", workspace, context))
        return {"guidance": [{"fragment_id": "TF-1", "memory_id": "TM-1", "guidance": "Ease back.",
                              "use_constraints": ["Advisory only."], "authority_layer": "advisory",
                              "confidence": 0.6}],
                "required_human_actions": [], "escalation_task_id": None}

    def agent_context(self, workspace, task, context, role=None):
        return {"task": task}

    def escalation(self, workspace, task_id):
        return {"task_id": task_id, "decision": None}


def test_tool_specs_for_openai_and_anthropic():
    toolbox = MetisToolbox(FakeClient(), "wsp_plant_a")
    openai = toolbox.openai_tools()
    anthropic = toolbox.anthropic_tools()
    assert [t["function"]["name"] for t in openai] == [t["name"] for t in anthropic]
    assert anthropic[0]["input_schema"]["required"] == ["context"]
    assert toolbox.openai_responses_tools()[0]["type"] == "function"
    result = toolbox.call("metis_retrieve_guidance", json.dumps({"context": PUMP}))
    assert result["guidance"][0]["fragment_id"] == "TF-1"
    assert toolbox.call("metis_check_escalation", {"task_id": "tsk_1"})["task_id"] == "tsk_1"
    with pytest.raises(KeyError):
        toolbox.call("metis_promote", {})


def test_langchain_tools_and_retriever():
    pytest.importorskip("langchain_core")
    from metis.integrations.langchain import MetisRetriever, metis_tools

    fake = FakeClient()
    tools = metis_tools(fake, "wsp_plant_a")
    assert [t.name for t in tools][0] == "metis_retrieve_guidance"
    out = tools[0].invoke({"context": PUMP})
    assert out["guidance"][0]["guidance"] == "Ease back."
    retriever = MetisRetriever(client=fake, workspace="wsp_plant_a", context_provider=lambda: PUMP)
    [doc] = retriever.invoke("how should I run the pump?")
    assert doc.page_content == "Ease back." and doc.metadata["use_constraints"] == ["Advisory only."]

    class Escalating(FakeClient):
        def retrieve(self, workspace, context, role=None):
            return {"guidance": [], "required_human_actions": ["A person decides first."],
                    "escalation_task_id": "tsk_9"}

    [held] = MetisRetriever(client=Escalating(), workspace="w", context=PUMP).invoke("q")
    assert held.metadata["type"] == "required_human_action"
    assert held.metadata["escalation_task_id"] == "tsk_9"
