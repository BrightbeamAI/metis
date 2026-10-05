import asyncio
import json
import os
import shutil
import sys

import pytest

import metis
from metis.mcp.tools import MetisTools
from metis.project import Project
from metis.scenarios import SPECS, run_spec

PUMP = SPECS["manufacturing-pump-vibration"]
MATCH = dict(PUMP.match_context)
WORKER = "human:operator@plant_a"


@pytest.fixture
def tools(tmp_path):
    project = Project(tmp_path)
    engine = project.create_engine(PUMP.workspace_id, name=PUMP.name, site=PUMP.site)
    run_spec(PUMP, engine=engine)
    project.save(engine)
    return MetisTools(project)


def test_guidance_comes_through_the_gate_and_is_recorded(tools):
    before = tools.engine.adapter.chain.count
    out = tools.retrieve_guidance(MATCH)
    assert out["guidance"] and out["guidance"][0]["use_constraints"]
    assert not out["required_human_actions"]
    assert tools.engine.adapter.chain.count > before
    assert tools.audit_verify()["ledger_agrees"]


def test_high_risk_withholds_guidance_and_names_a_person(tools):
    out = tools.retrieve_guidance({**MATCH, "risk_class": "high"})
    assert not out["guidance"]
    assert out["escalation_task_id"] and out["required_human_actions"]
    assert out["withheld"][0]["a_person_decides"] is True


def test_listing_never_returns_content(tools):
    listed = tools.list_tacit_memory()
    assert listed and all("guidance" not in m and "content" not in m and "use_constraints" not in m
                          for m in listed)


def test_capture_through_mcp_needs_the_workers_own_answer_and_consent(tools):
    asked = tools.submit_observation("OBS-M1", "Eased back at the dull note.", MATCH, WORKER,
                                     category="K7_sensory")
    assert asked["whisper_id"] and asked["question"]
    assert tools.list_pending_whispers(WORKER)[0]["whisper_id"] == asked["whisper_id"]
    with pytest.raises(PermissionError):
        tools.answer_whisper(asked["whisper_id"], "confirm", "agent:assistant#v1", "granted")
    stored = tools.answer_whisper(asked["whisper_id"], "confirm", WORKER, "granted")
    assert stored["stored"] and stored["authority_layer"] == "evidence" and stored["consent"] == "granted"


def test_declined_consent_stores_nothing(tools):
    asked = tools.submit_observation("OBS-M2", "Eased back at the dull note.", MATCH, WORKER)
    assert tools.answer_whisper(asked["whisper_id"], "confirm", WORKER, "declined")["stored"] is False


def test_evidence_layer_fragments_stay_invisible_to_agents(tools):
    asked = tools.submit_observation("OBS-M3", "Eased back at the dull note.", MATCH, WORKER,
                                     category="K7_sensory")
    stored = tools.answer_whisper(asked["whisper_id"], "confirm", WORKER, "granted")
    out = tools.retrieve_guidance(MATCH)
    assert out["not_yet_authorised"] == 1
    assert stored["fragment_id"] not in {w["fragment_id"] for w in out["withheld"]}
    assert stored["fragment_id"] not in {g["fragment_id"] for g in out["guidance"]}


def test_only_humans_submit_or_contest(tools):
    with pytest.raises(PermissionError):
        tools.submit_observation("OBS-M4", "x", MATCH, "agent:assistant#v1")
    with pytest.raises(PermissionError):
        tools.contest_fragment("TF-00001", "withdraw", "agent:assistant#v1", "no")
    out = tools.contest_fragment("TF-00001", "challenge", WORKER, "the cue is different now")
    assert out["recorded"] and out["mission_group_task"].startswith("tsk_")


def test_no_tool_can_grant_authority(tools):
    public = {n for n in dir(tools) if not n.startswith("_")}
    assert not any(w in n for n in public for w in ("promote", "review", "approve", "authorise", "revoke"))


def test_state_survives_between_tool_sessions(tools):
    asked = tools.submit_observation("OBS-M5", "Eased back at the dull note.", MATCH, WORKER)
    fresh = MetisTools(tools.project)
    assert fresh.list_pending_whispers()[0]["whisper_id"] == asked["whisper_id"]


EXPECTED_TOOLS = {"retrieve_guidance", "agent_memory_context", "list_tacit_memory",
                  "describe_workspace", "submit_observation", "list_pending_whispers",
                  "answer_whisper", "contest_fragment", "audit_verify", "audit_tail"}


def test_server_registers_exactly_the_governed_tools(tools):
    pytest.importorskip("mcp")
    from metis.mcp.server import build_server
    server = build_server(tools)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == EXPECTED_TOOLS


@pytest.mark.skipif(shutil.which("metis") is None, reason="metis console script not installed")
def test_end_to_end_over_stdio(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=["-m", "metis.cli.main", "mcp"],
                                       env={**os.environ, "METIS_HOME": str(tmp_path)})
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("retrieve_guidance", {"context": MATCH})
            text = "".join(getattr(c, "text", "") for c in result.content)
            info = getattr(init, "server_info", None) or init.serverInfo
            return {t.name for t in listed.tools}, json.loads(text), info

    names, decision, info = asyncio.run(scenario())
    assert names == EXPECTED_TOOLS
    assert decision["guidance"][0]["fragment_id"] == "TF-00001"
    assert info.name == "metis" and info.version == metis.__version__


def test_a_rejected_evidence_fragment_is_only_counted(tools):
    asked = tools.submit_observation("OBS-M9", "Eased back at the dull note.", MATCH, WORKER,
                                     category="K7_sensory")
    stored = tools.answer_whisper(asked["whisper_id"], "confirm", WORKER, "granted")
    eng = tools.engine
    eng.tier2_review(stored["fragment_id"], "rejected", summary="not enough evidence",
                     decided_by=[eng.mission_group_members[0]])
    out = tools.retrieve_guidance(MATCH)
    assert stored["fragment_id"] not in {w["fragment_id"] for w in out["withheld"]}
    assert out["not_yet_authorised"] >= 1


def test_a_held_fragment_drops_out_of_the_listing(tools):
    eng = tools.engine
    fragment_id = eng.fragments.all()[0].fragment_id
    assert fragment_id in {m["fragment_id"] for m in tools.list_tacit_memory()}
    eng.tier2_review(fragment_id, "held", decided_by=[eng.mission_group_members[2]],
                     summary="checking the new pump model")
    assert fragment_id not in {m["fragment_id"] for m in tools.list_tacit_memory()}
    assert not tools.retrieve_guidance(MATCH)["guidance"]


def test_an_overdue_fragment_drops_out_of_the_listing(tools):
    frag = tools.engine.fragments.all()[0]
    frag.review_due_at = "2000-01-01T00:00:00+00:00"
    assert frag.fragment_id not in {m["fragment_id"] for m in tools.list_tacit_memory()}


def test_retrieval_needs_the_situations_risk_class(tools):
    situation = {k: v for k, v in MATCH.items() if k != "risk_class"}
    with pytest.raises(ValueError, match="risk_class"):
        tools.retrieve_guidance(situation)
    with pytest.raises(ValueError, match="risk_class"):
        tools.agent_memory_context("inspect PUMP-A", situation)


def test_a_repeated_observation_asks_the_worker_once(tools):
    asked = tools.submit_observation("OBS-R1", "Eased back at the dull note.", MATCH, WORKER)
    again = tools.submit_observation("OBS-R1", "Eased back at the dull note.", MATCH, WORKER)
    assert again["repeated"] and again["whisper_id"] == asked["whisper_id"]
    assert len(tools.list_pending_whispers(WORKER)) == 1
    with pytest.raises(ValueError, match="reported already"):
        tools.submit_observation("OBS-R1", "Opened the vent first.", MATCH, WORKER)


# ---- the published tool definitions ------------------------------------------------------

def undocumented(schema):
    """Where a JSON Schema has a property, or a definition, with no description."""
    missing = []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for name, prop in node.get("properties", {}).items():
            if not prop.get("description"):
                missing.append(f"{path}.{name}")
            walk(prop, f"{path}.{name}")
        for key in ("items", "additionalProperties"):
            walk(node.get(key), f"{path}[]")
        for key in ("anyOf", "oneOf", "allOf"):
            for branch in node.get(key, []):
                walk(branch, path)

    walk(schema, "")
    for name, definition in schema.get("$defs", {}).items():
        if not definition.get("description"):
            missing.append(f"$defs.{name}")
        walk(definition, f"$defs.{name}")
    return missing


def check_definitions(listed):
    """Every tool states its purpose with a meaningful title, points to its siblings, declares
    every behaviour hint, and documents each argument and each returned field."""
    tools = [t.model_dump(by_alias=True, exclude_none=True) for t in listed]  # the wire form
    names = {t["name"] for t in tools}
    for t in tools:
        name, hints = t["name"], t.get("annotations", {})
        assert len(t.get("title", "")) > len(name), name
        assert len(t["description"]) > 200, name
        assert any(other in t["description"] for other in names - {name}), name
        assert {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"} <= set(hints)
        assert not undocumented(t["inputSchema"]), (name, undocumented(t["inputSchema"]))
        assert t.get("outputSchema"), name
        assert not undocumented(t["outputSchema"]), (name, undocumented(t["outputSchema"]))


def test_every_tool_is_fully_documented(tools):
    pytest.importorskip("mcp")
    from metis.mcp.server import build_server
    check_definitions(asyncio.run(build_server(tools).list_tools()))


def _call(server, name, arguments):
    """Call a tool in-process: the JSON of each text block, and the structured content."""
    result = asyncio.run(server.call_tool(name, arguments))
    if isinstance(result, tuple):  # mcp 1.x
        content, structured = result
        return [json.loads(c.text) for c in content], structured
    wire = result.model_dump(by_alias=True)
    if wire.get("isError"):
        raise AssertionError(wire["content"][0]["text"])
    return [json.loads(c["text"]) for c in wire["content"]], wire.get("structuredContent")


def test_every_result_carries_all_it_returns_in_its_schema(tools):
    """The structured result of each tool, validated against its output schema, keeps every
    key the tool returned: nothing is dropped on the way to the client."""
    pytest.importorskip("mcp")
    from metis.mcp.server import build_server
    server = build_server(tools)

    def call(name, **arguments):
        texts, structured = _call(server, name, arguments)
        if set(structured) == {"result"}:
            assert structured["result"] == texts, name
            return texts
        assert [structured] == texts, name
        return structured

    call("describe_workspace")
    assert call("list_tacit_memory")
    assert call("retrieve_guidance", context=MATCH, role="operator")["guidance"]
    assert call("retrieve_guidance", context={**MATCH, "risk_class": "high"})["withheld"]
    call("retrieve_guidance", context={**MATCH, "operating_mode": "startup"})
    call("agent_memory_context", task="inspect PUMP-A", context=MATCH)
    seen = {k: v for k, v in MATCH.items() if k != "risk_class"}
    asked = call("submit_observation", observation_id="OBS-S1", context=seen, worker=WORKER,
                 work_as_done="Eased back at the dull note.", category="K7_sensory")
    again = call("submit_observation", observation_id="OBS-S1", context=seen, worker=WORKER,
                 work_as_done="Eased back at the dull note.")
    assert again["repeated"] and again["whisper_id"] == asked["whisper_id"]
    assert call("list_pending_whispers", worker=WORKER)
    stored = call("answer_whisper", whisper_id=asked["whisper_id"], response="confirm",
                  answered_by=WORKER, consent="granted")
    assert stored["stored"]
    other = call("submit_observation", observation_id="OBS-S2", context=seen, worker=WORKER,
                 work_as_done="Opened the vent first.")
    assert not call("answer_whisper", whisper_id=other["whisper_id"], response="dismiss",
                    answered_by=WORKER, consent="declined")["stored"]
    assert call("contest_fragment", fragment_id="TF-00001", action="challenge",
                raised_by=WORKER, rationale="The cue is different now.")["mission_group_task"]
    assert call("contest_fragment", fragment_id="TF-00001", action="request_re_elicitation",
                raised_by=WORKER, rationale="Ask again after the refit.")["re_elicitation_request"]
    assert call("contest_fragment", fragment_id=stored["fragment_id"], action="withdraw",
                raised_by=WORKER, rationale="I take it back.")["revocation"]
    assert call("audit_verify")["verified"]
    assert len(call("audit_tail", limit=3)) == 3
    fitter = "human:fitter@plant_a"
    for n in range(6):
        last = call("submit_observation", observation_id=f"OBS-B{n}", context=seen,
                    worker=fitter, work_as_done=f"Changed the order of step {n}.")
    assert last["deferred"] and last["reason"]


def test_the_published_schema_refuses_what_metis_refuses(tools):
    pytest.importorskip("mcp")
    from metis.mcp.server import build_server
    server = build_server(tools)
    situation = {k: v for k, v in MATCH.items() if k != "risk_class"}
    for name, arguments in (
            ("retrieve_guidance", {"context": situation}),
            ("retrieve_guidance", {"context": {**MATCH, "valve": "open"}}),
            ("submit_observation", {"observation_id": "OBS-X", "work_as_done": "x",
                                    "context": situation, "worker": "agent:assistant#v1"}),
            ("answer_whisper", {"whisper_id": "w", "response": "maybe", "consent": "granted",
                                "answered_by": WORKER}),
            ("audit_tail", {"limit": 0})):
        with pytest.raises(Exception):  # noqa: B017 - the SDK's argument error differs by version
            _call(server, name, arguments)


def test_a_correction_carries_the_workers_own_words(tools):
    asked = tools.submit_observation("OBS-C1", "Eased back at the dull note.", MATCH, WORKER)
    with pytest.raises(ValueError, match="corrected_text"):
        tools.answer_whisper(asked["whisper_id"], "correct", WORKER, "granted")
    stored = tools.answer_whisper(asked["whisper_id"], "correct", WORKER, "granted",
                                  corrected_text="Eased back when the note dulled, not before.")
    assert stored["stored"]
