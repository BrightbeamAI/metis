import pytest

from metis.capture.loop import WhisperBudget
from metis.conditions.context import TacitContext
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.engine import MetisEngine
from metis.project import Project

CONSENT = ConsentRecord(consent_status=ConsentStatus.granted)
OBS = {"observation_id": "OBS-9", "work_as_imagined": "Run at the set speed.",
       "work_as_done": "Slowed the line when the resin looked glossy.",
       "context": TacitContext(product_family="resin_batch", operating_mode="inspection")}


def _engine(**kw):
    eng = MetisEngine(workspace_id="wsp_two_step", **kw)
    eng.join_default_participants()
    return eng


def test_whisper_then_the_workers_own_answer_stores_a_fragment():
    eng = _engine()
    pending = eng.begin_capture(OBS, consent=CONSENT, category="K5_material")
    assert pending.whisper_id and pending.whisper.question
    assert not eng.fragments.all()  # nothing is stored before the worker answers
    result = eng.answer_whisper(pending.whisper_id, response="confirm", answered_by=eng.operator_uri)
    assert result.fragment.authority_layer.value == "evidence"
    assert pending.whisper_id not in eng.pending_captures
    assert eng.verify().ok


def test_an_agent_cannot_answer_for_the_worker():
    eng = _engine()
    pending = eng.begin_capture(OBS, consent=CONSENT, category="K5_material")
    with pytest.raises(PermissionError):
        eng.answer_whisper(pending.whisper_id, response="confirm", answered_by="agent:assistant#v1")
    with pytest.raises(PermissionError):
        eng.answer_whisper(pending.whisper_id, response="confirm", answered_by="human:someone-else@plant_a")
    assert pending.whisper_id in eng.pending_captures


def test_a_dismissed_whisper_stores_nothing():
    eng = _engine()
    pending = eng.begin_capture(OBS, consent=CONSENT, category="K5_material")
    result = eng.answer_whisper(pending.whisper_id, response="dismiss", answered_by=eng.operator_uri)
    assert result.fragment is None and not eng.fragments.all()


def test_the_whisper_budget_defers_capture_and_records_it():
    eng = _engine(whisper_budget=WhisperBudget(max_per_worker=2, window_minutes=60))
    asked = [eng.begin_capture({**OBS, "observation_id": f"OBS-{i}"}, consent=CONSENT,
                               category="K5_material") for i in range(3)]
    assert [p.deferred for p in asked] == [False, False, True]
    events = [a["content"] for a in eng.adapter.artefacts_of_kind("tacit.validation_event")]
    assert any(e.get("event") == "whisper_deferred" for e in events)


def test_pending_whispers_survive_a_restart(tmp_path):
    project = Project(tmp_path)
    eng = project.create_engine("wsp_restart", name="Restart cell")
    eng.join_default_participants()
    pending = eng.begin_capture(OBS, consent=CONSENT, category="K5_material")
    project.save(eng)
    reopened = project.open("wsp_restart")
    result = reopened.answer_whisper(pending.whisper_id, response="confirm",
                                     answered_by=reopened.operator_uri)
    assert result.fragment is not None and reopened.verify().ok
