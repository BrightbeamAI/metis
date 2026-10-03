import datetime as dt

from metis import clock
from metis.engine import MetisEngine
from metis.scenarios import run_manufacturing


def _age_seconds(iso: str) -> float:
    stamp = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return abs((dt.datetime.now(dt.timezone.utc) - stamp).total_seconds())


def test_deterministic_engine_does_not_leak_its_clock():
    run_manufacturing()  # deterministic engine
    # Outside any engine call, records use real time.
    assert _age_seconds(clock.now_iso()) < 60


def test_live_engine_records_real_time_after_a_deterministic_run():
    run_manufacturing()
    live = MetisEngine(workspace_id="wsp_live", deterministic=False)
    live.join_default_participants()
    from metis.conditions.context import TacitContext
    from metis.consent.model import ConsentRecord, ConsentStatus
    res = live.capture_observation(
        {"observation_id": "LIVE-1", "work_as_done": "paused on a dull cue",
         "context": TacitContext(equipment_family="centrifugal_pump")},
        consent=ConsentRecord(consent_status=ConsentStatus.granted), category="K7_sensory")
    assert _age_seconds(res.fragment.created_at) < 60


def test_deterministic_runs_are_reproducible():
    a = run_manufacturing().fragment
    b = run_manufacturing().fragment
    assert a.created_at == b.created_at
    assert a.lineage[-1].at == b.lineage[-1].at


def test_api_records_real_time():
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from metis.api import routes
    from metis.api.server import app
    routes.reset_engine()
    client = TestClient(app)
    r = client.post("/capture", json={"observation_id": "API-1", "work_as_done": "paused on a dull cue",
                                      "context": {"equipment_family": "centrifugal_pump"},
                                      "category": "K7_sensory"})
    assert r.status_code == 200
    assert _age_seconds(r.json()["fragment"]["created_at"]) < 60


def test_api_rejects_unsafe_export_paths_and_non_promotion_outcomes():
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from metis.api.server import app
    client = TestClient(app)
    assert client.post("/audit/export", params={"out": "../../etc/evil.jsonl"}).status_code == 422
    assert client.post("/audit/export", params={"out": "/tmp/evil.jsonl"}).status_code == 422
    r = client.post("/promote", json={"fragment_id": "TF-00001", "outcome": "rejected"})
    assert r.status_code == 422
