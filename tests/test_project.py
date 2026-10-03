import json

import pytest
from typer.testing import CliRunner

from metis.audit.ledger import LedgerMismatch
from metis.cli.main import app
from metis.conditions.context import TacitContext
from metis.project import Project
from metis.scenarios import SPECS, run_spec

PUMP = SPECS["manufacturing-pump-vibration"]
runner = CliRunner()


def _run_into(project, spec=PUMP):
    workspace_id = project.unique_workspace_id(spec.workspace_id)
    engine = project.create_engine(workspace_id, name=spec.name, site=spec.site)
    run_spec(spec, engine=engine)
    project.save(engine)
    return engine


def _lines(path):
    return path.read_text().count("\n")


def test_chain_continues_across_reopen(tmp_path):
    project = Project(tmp_path)
    first = _run_into(project)
    n = first.adapter.chain.count
    again = project.open()
    assert again.adapter.chain.count == n and len(again.fragments.all()) == 1
    again.retrieve(TacitContext(**PUMP.match_context))
    project.save(again)
    assert again.adapter.chain.entries[n].seq == n
    assert again.verify().ok
    assert _lines(project.ledger_path(PUMP.workspace_id)) == again.adapter.chain.count


def test_a_second_run_never_overwrites_the_first(tmp_path):
    project = Project(tmp_path)
    _run_into(project)
    ledger = project.ledger_path(PUMP.workspace_id)
    before = ledger.read_text()
    second = _run_into(project)
    assert second.adapter.workspace_id == PUMP.workspace_id + "-2"
    assert ledger.read_text() == before
    assert project.workspace_ids() == [PUMP.workspace_id, PUMP.workspace_id + "-2"]


def test_ledger_ahead_of_store_is_detected(tmp_path):
    project = Project(tmp_path)
    _run_into(project)
    project.chap_db.unlink()  # the coordinator state is lost; the ledger survives
    with pytest.raises(LedgerMismatch):
        project.open()


def test_cli_records_retrievals_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setenv("METIS_HOME", str(tmp_path))
    ctx = tmp_path / "ctx.json"
    ctx.write_text(json.dumps({**PUMP.match_context, "risk_class": "high"}))
    assert runner.invoke(app, ["demo", "manufacturing-pump-vibration"]).exit_code == 0
    ledger = Project(tmp_path).ledger_path(PUMP.workspace_id)
    before = _lines(ledger)
    out = runner.invoke(app, ["retrieve", "--context", str(ctx)])
    assert out.exit_code == 0 and "ESCALATED to a person" in out.output
    assert _lines(ledger) > before
    verify = runner.invoke(app, ["audit", "verify"])
    assert verify.exit_code == 0 and "Store and ledger agree: True" in verify.output


def test_cli_detects_a_tampered_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("METIS_HOME", str(tmp_path))
    assert runner.invoke(app, ["demo", "manufacturing-pump-vibration"]).exit_code == 0
    ledger = Project(tmp_path).ledger_path(PUMP.workspace_id)
    lines = ledger.read_text().splitlines()
    record = json.loads(lines[5])
    record["envelope"]["params"]["from"] = "human:intruder@plant_a"
    lines[5] = json.dumps(record, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n")
    assert runner.invoke(app, ["audit", "verify"]).exit_code == 1


def test_cli_without_a_project_explains_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("METIS_HOME", str(tmp_path))
    out = runner.invoke(app, ["fragment", "list"])
    assert out.exit_code != 0 and "metis demo" in out.output


def test_workspace_list_and_use(tmp_path, monkeypatch):
    monkeypatch.setenv("METIS_HOME", str(tmp_path))
    runner.invoke(app, ["demo", "manufacturing-pump-vibration"])
    runner.invoke(app, ["demo", "shift-handover-gap"])
    listed = runner.invoke(app, ["workspace", "list"]).output
    assert "* wsp_shift_handover" in listed and "wsp_pump_vibration" in listed
    assert runner.invoke(app, ["workspace", "use", "wsp_pump_vibration"]).exit_code == 0
    assert "wsp_pump_vibration" in runner.invoke(app, ["workspace", "describe"]).output
