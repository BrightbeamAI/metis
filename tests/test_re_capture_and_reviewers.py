"""A re-elicited fragment is replaced by a new capture; live engines record named reviewers."""
import pytest

from metis.conditions.context import TacitContext
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.engine import MetisEngine
from metis.validation.states import InvalidTransition

QL = "human:quality-lead@metis.local"
PE = "human:process-engineer@metis.local"
QUORUM = [QL, PE]
OBS = {"observation_id": "OBS-R1",
       "work_as_imagined": "Reduce load only when the alarm threshold is crossed.",
       "work_as_done": "Ease back at the first dull note, before the vibration rises."}


def _re_elicited(engine, res):
    fragment_id = res.fragment.fragment_id
    engine.tier2_review(fragment_id, "promoted_to_advisory", decided_by=QUORUM, summary="ok")
    engine.tier2_review(fragment_id, "re_elicit", decided_by=[PE], summary="cue unclear")
    return engine.fragments.get(fragment_id)


def test_a_new_capture_replaces_a_re_elicited_fragment(captured_fragment, granted_consent,
                                                       match_context):
    engine, res = captured_fragment
    old = _re_elicited(engine, res)
    pending = engine.begin_capture({**OBS, "context": match_context}, consent=granted_consent,
                                   category="K7_sensory", conditions=match_context,
                                   supersedes=old.fragment_id)
    result = engine.answer_whisper(pending.whisper_id, response="confirm",
                                   answered_by=engine.operator_uri, consent_granted=True)

    new_id = result.fragment.fragment_id
    assert result.superseded == old.fragment_id
    assert old.validation_state.value == "superseded"
    assert old.revocation_status.value == "superseded"
    record = engine.adapter.artefacts_of_kind("tacit.supersession_record")[-1]["content"]
    assert record["superseded"] == old.fragment_id and record["superseded_by"] == new_id

    # The replacement goes through review like any other capture.
    engine.tier2_review(new_id, "promoted_to_advisory", decided_by=QUORUM, summary="re-elicited")
    assert engine.evaluate(result.fragment, match_context).ok
    assert not engine.evaluate(old, match_context).ok
    assert engine.verify().ok


def test_only_a_fragment_awaiting_re_elicitation_can_be_replaced(captured_fragment,
                                                                 granted_consent, match_context):
    engine, res = captured_fragment
    engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", decided_by=QUORUM)
    before = engine.adapter.chain.count
    with pytest.raises(InvalidTransition, match="awaits re-elicitation"):
        engine.begin_capture({**OBS, "context": match_context}, consent=granted_consent,
                             category="K7_sensory", supersedes=res.fragment.fragment_id)
    assert engine.adapter.chain.count == before


def test_a_dismissed_re_capture_leaves_the_fragment_awaiting_re_elicitation(
        captured_fragment, granted_consent, match_context):
    engine, res = captured_fragment
    old = _re_elicited(engine, res)
    result = engine.capture_observation({**OBS, "context": match_context},
                                        consent=granted_consent, category="K7_sensory",
                                        response="dismiss", supersedes=old.fragment_id)
    assert result.fragment is None and result.superseded is None
    assert old.validation_state.value == "re_elicit"


def test_a_live_engine_records_decisions_only_with_named_reviewers():
    engine = MetisEngine(workspace_id="wsp_named", deterministic=False)
    engine.join_default_participants()
    res = engine.capture_observation(
        {"observation_id": "LIVE-R1", "work_as_done": "paused on a dull cue",
         "context": TacitContext(equipment_family="centrifugal_pump")},
        consent=ConsentRecord(consent_status=ConsentStatus.granted), category="K7_sensory")
    fragment_id = res.fragment.fragment_id
    before = engine.adapter.chain.count
    for outcome in ("promoted_to_advisory", "held", "rejected"):
        with pytest.raises(PermissionError, match="Name the reviewers"):
            engine.tier2_review(fragment_id, outcome)
    assert engine.adapter.chain.count == before
    out = engine.tier2_review(fragment_id, "promoted_to_advisory", decided_by=QUORUM)
    assert out["decided_by"] == QUORUM


def test_the_api_asks_for_named_reviewers():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from metis.api import routes
    from metis.api.server import app

    routes.reset_engine()
    client = TestClient(app)
    anonymous = client.post("/review", json={"fragment_id": "TF-00001", "outcome": "held"})
    assert anonymous.status_code == 422 and "decided_by" in anonymous.json()["detail"]
    named = client.post("/review", json={"fragment_id": "TF-00001", "outcome": "held",
                                         "decided_by": ["human:safety-officer@metis.local"]})
    assert named.status_code == 200
    routes.reset_engine()
