"""Capture connectors: source mappings, ingestion, and the import command."""
import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from metis.cli.main import app as cli
from metis.connectors.mapping import (
    SourceMapping,
    get_path,
    load_mappings,
    map_records,
    passes,
    read_records,
    resolve,
)
from metis.identity import ApiKeyAuthenticator, ApiKeyEntry, AuthenticatorChain
from metis.server.app import create_app
from metis.server.settings import ServerSettings
from metis.storage.sql import SqlRepository

MAPPINGS = """
sources:
  cmms:
    records: $.items
    id: $.work_order.id
    worker: $.work_order.technician
    worker_map: {T-17: "human:walt@example.com"}
    work_as_done: $.work_order.action_taken
    work_as_imagined: $.work_order.procedure_step
    title: "Work order {work_order.id}"
    category: K4_equipment_specific
    when: $.work_order.deviation == true
    context:
      equipment_family: $.asset.family
      equipment_id: $.asset.id
      site: plant_a
"""


def _record(wo, tech, deviation=True, action="Swapped the seal before the run."):
    return {"work_order": {"id": wo, "technician": tech, "action_taken": action,
                           "procedure_step": "Swap seals at the quarterly stop.",
                           "deviation": deviation},
            "asset": {"family": "centrifugal_pump", "id": "PUMP-A"}}


def test_paths_templates_and_filters():
    rec = {"a": {"b": [{"c": 3}]}, "Action taken": "x", "flag": "false"}
    assert get_path(rec, "$.a.b[0].c") == 3 and get_path(rec, "$['Action taken']") == "x"
    assert get_path(rec, "$.a.missing.c") is None and get_path(rec, "$.a.b[9]") is None
    assert resolve("C is {a.b[0].c}", rec) == "C is 3" and resolve("plain", rec) == "plain"
    assert passes("$.a.b[0].c == 3", rec) and passes("$['Action taken'] != y", rec)
    assert not passes("$.flag", rec) and passes("not $.flag", rec)
    with pytest.raises(ValueError):
        get_path(rec, "a.b")


def test_a_mapping_turns_records_into_observations(tmp_path):
    path = tmp_path / "connectors.yaml"
    path.write_text(MAPPINGS)
    mapping = load_mappings(path)["cmms"]
    payload = {"items": [_record(1, "Wendy@Example.com"), _record(2, "T-17"),
                         _record(3, "wendy@example.com", deviation=False), _record(4, "nobody")]}
    records = mapping.records_in(payload)
    mapped, failed = map_records(mapping, records)
    assert [m.observation_id for m in mapped] == ["cmms:1", "cmms:2"]
    assert mapped[0].worker == "human:wendy@example.com" and mapped[1].worker == "human:walt@example.com"
    assert mapped[0].title == "Work order 1" and mapped[0].context == {
        "equipment_family": "centrifugal_pump", "equipment_id": "PUMP-A", "site": "plant_a"}
    assert failed == [{"record": 3, "error": "Unknown worker 'nobody': add it to worker_map, or map an email field."}]
    with pytest.raises(ValueError):
        SourceMapping(name="x", id="$.id", worker="$.w", work_as_done="$.d").map({"w": "a@b.co", "d": "x"})


def test_records_from_csv_and_json_lines(tmp_path):
    csv_file = tmp_path / "orders.csv"
    csv_file.write_text("id,technician,Action taken\n7,wendy@example.com,Opened the vent\n")
    [row] = read_records(csv_file)
    assert row["Action taken"] == "Opened the vent"
    lines = tmp_path / "orders.jsonl"
    lines.write_text(json.dumps({"id": 1}) + "\n\n" + json.dumps({"id": 2}) + "\n")
    assert [r["id"] for r in read_records(lines)] == [1, 2]


@pytest.fixture()
def server(tmp_path):
    (tmp_path / "connectors.yaml").write_text(MAPPINGS)
    keys, entries = {}, []
    for name, uri in {"admin": "human:admin@example.com", "cmms": "agent:cmms-connector",
                      "agent": "agent:shift-assistant", "wendy": "human:wendy@example.com"}.items():
        key, digest = ApiKeyAuthenticator.generate()
        keys[name] = key
        entries.append(ApiKeyEntry(id=name, sha256=digest, uri=uri,
                                   global_roles=("admin",) if name == "admin" else ()))
    repo = SqlRepository(f"sqlite:///{tmp_path / 'c.db'}")
    app = create_app(ServerSettings(connectors_file=str(tmp_path / "connectors.yaml")),
                     repository=repo, authenticator=AuthenticatorChain([ApiKeyAuthenticator(entries)]))
    client = TestClient(app)

    def as_(name):
        return {"Authorization": f"Bearer {keys[name]}"}

    client.post("/v1/workspaces", headers=as_("admin"), json={
        "id": "wsp_plant_a", "name": "Plant A", "members": [
            {"uri": "human:wendy@example.com", "roles": ["worker"]},
            {"uri": "agent:cmms-connector", "roles": ["capture"]},
            {"uri": "agent:shift-assistant", "roles": ["agent"]}]})
    yield client, as_, repo, tmp_path
    repo.close()


def test_ingesting_records_captures_each_new_one_once(server):
    client, as_, repo, tmp_path = server
    url = "/v1/workspaces/wsp_plant_a/ingest/cmms"
    payload = {"items": [_record(1, "wendy@example.com"), _record(2, "T-17"),
                         _record(3, "wendy@example.com", deviation=False),
                         {**_record(5, "wendy@example.com"), "asset": {"family": "centrifugal_pump"}}]}
    result = client.post(url, headers=as_("cmms"), json=payload).json()
    assert [a["observation_id"] for a in result["accepted"]] == ["cmms:1", "cmms:5"]
    assert result["filtered"] == 1 and result["duplicates"] == []
    assert result["failed"] == [{"observation_id": "cmms:2",
                                 "error": "human:walt@example.com is not a worker in wsp_plant_a."}]
    again = client.post(url, headers=as_("cmms"), json=payload).json()
    assert again["accepted"] == [] and again["duplicates"] == ["cmms:1", "cmms:5"]
    whispers = client.get("/v1/workspaces/wsp_plant_a/whispers", headers=as_("wendy")).json()
    assert len(whispers) == 2 and {w["submitted_by"] for w in whispers} == {"agent:cmms-connector"}
    assert client.post(url, headers=as_("agent"), json=payload).status_code == 403
    assert client.post("/v1/workspaces/wsp_plant_a/ingest/erp", headers=as_("cmms"),
                       json=payload).status_code == 404
    assert client.get("/v1/connectors", headers=as_("cmms")).json()[0]["source"] == "cmms"


def test_the_import_command_checks_and_imports(server, monkeypatch):
    client, as_, repo, tmp_path = server
    records = tmp_path / "orders.json"
    records.write_text(json.dumps({"items": [_record(10, "wendy@example.com"),
                                             _record(11, "wendy@example.com", deviation=False)]}))
    lines = tmp_path / "orders.jsonl"
    lines.write_text(json.dumps(_record(12, "wendy@example.com")) + "\n")
    monkeypatch.setenv("METIS_CONNECTORS_FILE", str(tmp_path / "connectors.yaml"))
    monkeypatch.setenv("METIS_DATABASE_URL", repo.url)
    runner = CliRunner()
    checked = json.loads(runner.invoke(cli, ["connector", "check", "--source", "cmms",
                                             "--file", str(records)]).output)
    assert [o["observation_id"] for o in checked["observations"]] == ["cmms:10"]
    assert checked["filtered"] == 1
    imported = runner.invoke(cli, ["connector", "import", "--workspace", "wsp_plant_a",
                                   "--source", "cmms", "--file", str(lines),
                                   "--as", "agent:cmms-connector"])
    assert imported.exit_code == 0, imported.output
    assert json.loads(imported.output)["accepted"] == 1
    refused = runner.invoke(cli, ["connector", "import", "--workspace", "wsp_plant_a",
                                  "--source", "cmms", "--file", str(lines),
                                  "--as", "agent:shift-assistant"])
    assert refused.exit_code != 0
