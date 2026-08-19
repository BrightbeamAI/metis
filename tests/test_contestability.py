from metis.consent.contestability import ContestAction
from metis.retrieval.gate import RetrievalGate
from metis.taxonomy.categories import RevocationStatus

GATE = RetrievalGate()


def _promote(engine, res):
    engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", summary="ok")
    return res.fragment


def test_challenge_records_event_and_escalates_to_mission_group(captured_fragment):
    engine, res = captured_fragment
    out = engine.governance.contest(
        res.fragment.fragment_id, ContestAction.challenge,
        raised_by=engine.operator_uri, rationale="the cue description is wrong")
    assert out["contestability_record"].startswith("art_")
    events = engine.adapter.artefacts_of_kind("tacit.validation_event")
    assert any(a["content"].get("event") == "contestability" for a in events)
    task = engine.adapter.tasks[out["escalated_task"]]
    assert task["assignee"] == engine.mission_group_uri
    assert task["kind"] == "tacit.validate.tier2"
    assert engine.verify().ok


def test_correct_carries_the_proposed_correction(captured_fragment):
    engine, res = captured_fragment
    out = engine.governance.contest(
        res.fragment.fragment_id, ContestAction.correct,
        raised_by=engine.operator_uri, rationale="wording is off",
        proposed_correction="reduce throughput only above 40 degrees")
    rec = engine.adapter.artefacts[out["contestability_record"]]
    assert rec["content"]["proposed_correction"] == "reduce throughput only above 40 degrees"
    assert rec["content"]["action"] == "correct"


def test_withdraw_revokes_and_blocks_retrieval(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    assert GATE.evaluate(frag, match_context).ok
    out = engine.governance.contest(
        frag.fragment_id, ContestAction.withdraw,
        raised_by=engine.operator_uri, rationale="withdrawing my contribution")
    assert "revocation" in out and "contestability_record" in out
    assert frag.revocation_status == RevocationStatus.withdrawn
    assert not GATE.evaluate(frag, match_context).ok


def test_re_elicitation_creates_request_and_mission_group_task(captured_fragment):
    engine, res = captured_fragment
    out = engine.governance.contest(
        res.fragment.fragment_id, ContestAction.request_re_elicitation,
        raised_by=engine.operator_uri, rationale="conditions are too broad")
    assert out["re_elicitation_request"].startswith("art_")
    assert any(a["kind"] == "tacit.re_elicitation_request" for a in engine.adapter.artefacts.values())
    assert any(t["kind"] == "tacit.re_elicit" and t["assignee"] == engine.mission_group_uri
               for t in engine.adapter.tasks.values())
    assert engine.verify().ok
