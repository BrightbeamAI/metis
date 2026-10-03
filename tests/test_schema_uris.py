"""The schema URI an artefact carries names the published schema for its kind."""
import json
from pathlib import Path

from metis.capture.loop import WhisperBudget
from metis.consent.contestability import ContestAction
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.engine import MetisEngine
from metis.scenarios import SPECS, run_spec
from metis.validation.events import ValidationEvent

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = {json.loads(p.read_text())["$id"] for p in (ROOT / "schemas").glob("*.schema.json")}
OBS = {"observation_id": "OBS-X", "work_as_imagined": "Run the mixer at the set speed.",
       "work_as_done": "Slow the mixer when the lot feels damp."}


def test_core_artefacts_name_a_published_schema():
    run = run_spec(SPECS["manufacturing-pump-vibration"])
    schema_of = {a["kind"]: a["schema"] for a in run.engine.adapter.artefacts.values()
                 if a.get("schema")}
    for kind in ("tacit.fragment", "tacit.memory_object", "tacit.retrieval_decision",
                 "tacit.review_decision", "tacit.promotion_record", "tacit.agent_memory_context",
                 "tacit.model_assist_record"):
        assert schema_of[kind] in PUBLISHED, kind


def test_validation_events_match_their_model_and_schema():
    eng = MetisEngine(whisper_budget=WhisperBudget(max_per_worker=1, window_minutes=60))
    eng.join_default_participants()
    pending = ConsentRecord(consent_status=ConsentStatus.pending)
    first = eng.begin_capture(OBS, consent=pending, category="K5_material")
    eng.answer_whisper(first.whisper_id, response="confirm", answered_by=eng.operator_uri,
                       consent_granted=False)
    eng.begin_capture({**OBS, "observation_id": "OBS-Y"}, consent=pending, category="K5_material")

    run = run_spec(SPECS["manufacturing-pump-vibration"])
    run.engine.governance.contest(run.fragment.fragment_id, ContestAction.challenge,
                                  raised_by=run.engine.operator_uri, rationale="check the cue")

    events = (eng.adapter.artefacts_of_kind("tacit.validation_event")
              + run.engine.adapter.artefacts_of_kind("tacit.validation_event"))
    for art in events:
        ValidationEvent.model_validate(art["content"])
        assert art["schema"] in PUBLISHED
    assert {a["content"]["event"] for a in events} == {
        "consent_declined", "whisper_deferred", "contestability"}
