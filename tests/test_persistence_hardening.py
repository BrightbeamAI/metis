import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from metis.audit.ledger import LedgerMismatch
from metis.conditions.context import TacitContext
from metis.consent.contestability import ContestAction
from metis.project import Project, WorkspaceBusy
from metis.scenarios import SPECS, run_spec

ROOT = Path(__file__).resolve().parents[1]
PUMP = SPECS["manufacturing-pump-vibration"]
MATCH = TacitContext(**PUMP.match_context)

HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[3])
from metis.project import Project
Project(sys.argv[1]).open(sys.argv[2])
print("ready", flush=True)
time.sleep(60)
"""


def _project_with_pump(tmp_path):
    project = Project(tmp_path)
    engine = project.create_engine(PUMP.workspace_id, name=PUMP.name, site=PUMP.site)
    run_spec(PUMP, engine=engine)
    project.save(engine)
    return project, engine


def test_sqlite_holds_the_authoritative_domain_state(tmp_path):
    project, _ = _project_with_pump(tmp_path)
    workspace = project.workspace_dir(PUMP.workspace_id)
    assert not (workspace / "state.json").exists()
    con = sqlite3.connect(project.state_db(PUMP.workspace_id))
    rows = con.execute("SELECT id, authority_layer FROM fragments").fetchall()
    assert rows == [("TF-00001", "advisory")]
    reopened = project.open()
    assert reopened.fragments.require("TF-00001").authority_layer.value == "advisory"
    assert len(reopened.procedural.entries) == len(PUMP.procedural)


def test_a_second_writer_is_refused_while_the_first_runs(tmp_path):
    project, _ = _project_with_pump(tmp_path)
    project.close(PUMP.workspace_id)
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(tmp_path), PUMP.workspace_id, str(ROOT)],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ready"
        with pytest.raises(WorkspaceBusy):
            Project(tmp_path).open()
        # Inspection and verification still work alongside the writer.
        reader = Project(tmp_path).open(read_only=True)
        assert reader.verify().ok
        with pytest.raises(PermissionError):
            reader.retrieve(MATCH)
    finally:
        holder.terminate()
        holder.wait()
    assert Project(tmp_path).open().verify().ok  # the lock went with the process


def test_the_ledger_refuses_writes_it_did_not_make(tmp_path):
    project, engine = _project_with_pump(tmp_path)
    with project.ledger_path(PUMP.workspace_id).open("a") as fh:
        fh.write(json.dumps({"seq": 999}) + "\n")
    with pytest.raises(LedgerMismatch):
        engine.retrieve(MATCH)


def test_only_the_contributing_worker_can_withdraw_consent(tmp_path):
    _, engine = _project_with_pump(tmp_path)
    events_before = len(engine.adapter.artefacts_of_kind("tacit.validation_event"))
    with pytest.raises(PermissionError):
        engine.governance.contest("TF-00001", ContestAction.withdraw,
                                  raised_by="human:someone-else@plant_a", rationale="no")
    with pytest.raises(PermissionError):
        engine.governance.withdraw_consent("TF-00001", by="human:quality-lead@metis.local")
    assert len(engine.adapter.artefacts_of_kind("tacit.validation_event")) == events_before
    out = engine.governance.contest("TF-00001", ContestAction.withdraw,
                                    raised_by=engine.operator_uri, rationale="mine to withdraw")
    assert "revocation" in out


def test_saving_requires_the_writer_lock(tmp_path):
    project, _ = _project_with_pump(tmp_path)
    reader = project.open(read_only=True)
    project.close(PUMP.workspace_id)
    with pytest.raises(WorkspaceBusy):
        project.save(reader)


def test_an_unknown_category_records_nothing(tmp_path):
    from metis.consent.model import ConsentRecord, ConsentStatus
    _, engine = _project_with_pump(tmp_path)
    before = engine.adapter.chain.count
    with pytest.raises(ValueError):
        engine.begin_capture({"observation_id": "X", "work_as_done": "y", "context": MATCH},
                             consent=ConsentRecord(consent_status=ConsentStatus.pending),
                             category="K99_made_up")
    assert engine.adapter.chain.count == before


def test_audit_verify_compares_the_ledger_with_the_store_entry_by_entry(tmp_path):
    from metis.scenarios import SPECS, run_spec

    spec = SPECS["manufacturing-pump-vibration"]
    project = Project(tmp_path)
    engine = project.create_engine(spec.workspace_id, name=spec.name, site=spec.site)
    run_spec(spec, engine=engine)
    project.save(engine)
    assert engine.adapter.ledger.matches(engine.adapter)

    path = project.ledger_path(spec.workspace_id)
    lines = path.read_text().splitlines()
    record = json.loads(lines[3])
    record["method_or_type"] = "decide.approve"  # a field outside the hash link
    lines[3] = json.dumps(record, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")

    project.close(spec.workspace_id)
    reopened = project.open(spec.workspace_id, read_only=True)
    assert not reopened.adapter.ledger.matches(reopened.adapter)
