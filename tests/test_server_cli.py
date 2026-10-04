"""``metis server`` administration commands against a SQLite database."""
from typer.testing import CliRunner

from metis.cli.main import app

runner = CliRunner()


def test_workspaces_members_and_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("METIS_DATABASE_URL", f"sqlite:///{tmp_path / 'server.db'}")
    monkeypatch.setenv("METIS_API_KEYS_FILE", str(tmp_path / "keys.yaml"))
    assert "schema version 3" in runner.invoke(app, ["server", "migrate"]).output
    created = runner.invoke(app, ["server", "workspace", "create", "--id", "wsp_plant_a",
                                  "--name", "Plant A", "--admin", "human:ana@example.com"])
    assert created.exit_code == 0, created.output
    assert "wsp_plant_a" in runner.invoke(app, ["server", "workspace", "list"]).output
    member = runner.invoke(app, ["server", "member", "set", "--workspace", "wsp_plant_a",
                                 "--uri", "human:rhea@example.com", "--roles", "reviewer"])
    assert "reviewer" in member.output
    listed = runner.invoke(app, ["server", "member", "list", "--workspace", "wsp_plant_a"]).output
    assert "human:ana@example.com  admin" in listed and "human:rhea@example.com  reviewer" in listed
    bad = runner.invoke(app, ["server", "member", "set", "--workspace", "wsp_plant_a",
                              "--uri", "agent:bot", "--roles", "reviewer"])
    assert bad.exit_code != 0

    issued = runner.invoke(app, ["server", "api-key", "create", "--id", "assistant",
                                 "--uri", "agent:shift-assistant"])
    assert issued.exit_code == 0 and issued.stdout.strip().startswith("metis_")
    assert issued.stdout.strip() not in (tmp_path / "keys.yaml").read_text()
    assert "agent:shift-assistant" in runner.invoke(app, ["server", "api-key", "list"]).output
    duplicate = runner.invoke(app, ["server", "api-key", "create", "--id", "assistant",
                                    "--uri", "agent:other"])
    assert duplicate.exit_code == 1
    assert runner.invoke(app, ["server", "api-key", "revoke", "--id", "assistant"]).exit_code == 0
    assert runner.invoke(app, ["server", "api-key", "revoke", "--id", "assistant"]).exit_code == 1


def test_sweep_and_the_outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("METIS_DATABASE_URL", f"sqlite:///{tmp_path / 'server.db'}")
    monkeypatch.setenv("METIS_NOTIFY_LOG", "1")
    created = runner.invoke(app, ["server", "workspace", "create", "--id", "wsp_plant_a",
                                  "--name", "Plant A", "--admin", "human:ana@example.com"])
    assert created.exit_code == 0, created.output
    listed = runner.invoke(app, ["server", "outbox", "list"]).output
    assert "member.changed" in listed and "pending" in listed
    assert '"delivered": 1' in runner.invoke(app, ["server", "outbox", "deliver"]).output
    assert "delivered" in runner.invoke(app, ["server", "outbox", "list",
                                              "--status", "delivered"]).output
    swept = runner.invoke(app, ["server", "sweep"])
    assert swept.exit_code == 0 and '"workspaces": 1' in swept.output
