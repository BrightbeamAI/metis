import asyncio
import json
import os
import shutil
import sys

import pytest

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
            await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("retrieve_guidance", {"context": MATCH})
            text = "".join(getattr(c, "text", "") for c in result.content)
            return {t.name for t in listed.tools}, json.loads(text)

    names, decision = asyncio.run(scenario())
    assert names == EXPECTED_TOOLS
    assert decision["guidance"][0]["fragment_id"] == "TF-00001"


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
