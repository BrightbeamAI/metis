"""The inbox across workspaces, escalation decisions, the web app shell, and background sweeps."""
import datetime as dt
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from metis.identity import ApiKeyAuthenticator, ApiKeyEntry, AuthenticatorChain
from metis.notify import Channel, Dispatcher, Notifier
from metis.server.app import create_app
from metis.server.background import sweep
from metis.server.settings import ServerSettings
from metis.storage.sql import SqlRepository

WS = "wsp_plant_a"
PEOPLE = {"admin": "human:admin@example.com", "wendy": "human:wendy@example.com",
          "walt": "human:walt@example.com", "rhea": "human:rhea@example.com",
          "raj": "human:raj@example.com", "agent": "agent:shift-assistant",
          "cmms": "agent:cmms-connector"}
PUMP = {"equipment_family": "centrifugal_pump", "operating_mode": "high_load"}


@dataclass
class Recorder(Channel):
    sent: list = field(default_factory=list)

    def recipients_for(self, n):
        return list(n.recipients)

    def deliver(self, n, recipient, delivery_id):
        self.sent.append((n.event, recipient))


@pytest.fixture()
def server(tmp_path):
    keys, entries = {}, []
    for name, uri in PEOPLE.items():
        key, digest = ApiKeyAuthenticator.generate()
        keys[name] = key
        entries.append(ApiKeyEntry(id=name, sha256=digest, uri=uri,
                                   global_roles=("admin",) if name == "admin" else ()))
    recorder = Recorder(name="people", personal=True)
    repo = SqlRepository(f"sqlite:///{tmp_path / 's.db'}", notifier=Notifier([recorder]))
    settings = ServerSettings(api_keys_file=str(tmp_path / "keys.yaml"))
    app = create_app(settings, repository=repo,
                     authenticator=AuthenticatorChain([ApiKeyAuthenticator(entries)]))
    client = TestClient(app)

    def as_(name):
        return {"Authorization": f"Bearer {keys[name]}"}

    members = [{"uri": PEOPLE["wendy"], "roles": ["worker"]},
               {"uri": PEOPLE["walt"], "roles": ["worker"]},
               {"uri": PEOPLE["rhea"], "roles": ["reviewer"]},
               {"uri": PEOPLE["raj"], "roles": ["reviewer", "escalation"]},
               {"uri": PEOPLE["agent"], "roles": ["agent"]},
               {"uri": PEOPLE["cmms"], "roles": ["capture"]}]
    assert client.post("/v1/workspaces", headers=as_("admin"), json={
        "id": WS, "name": "Plant A", "members": members,
        "whisper_deadline_hours": 1}).status_code == 201
    yield client, as_, repo, recorder, app
    repo.close()


def _observe(client, as_):
    return client.post(f"/v1/workspaces/{WS}/observations", headers=as_("cmms"), json={
        "observation_id": "WO-1", "work_as_done": "Eased back earlier on a dull sound.",
        "work_as_imagined": "Reduce load at the alarm.", "context": PUMP,
        "worker": PEOPLE["wendy"], "category": "K7_sensory"}).json()


def test_each_person_sees_what_awaits_them(server):
    client, as_, repo, recorder, app = server
    whisper = _observe(client, as_)
    inbox = client.get("/v1/me/inbox", headers=as_("wendy")).json()
    [item] = inbox["whispers"]
    assert item["whisper_id"] == whisper["whisper_id"] and item["workspace"]["name"] == "Plant A"
    assert item["deadline_at"] and item["work_as_imagined"] == "Reduce load at the alarm."
    assert client.get("/v1/me/inbox", headers=as_("walt")).json()["whispers"] == []

    client.post(f"/v1/workspaces/{WS}/whispers/{whisper['whisper_id']}/answer",
                headers=as_("wendy"), json={"response": "confirm", "consent": "granted"})
    [review] = client.get("/v1/me/inbox", headers=as_("rhea")).json()["reviews"]
    fid = review["fragment_id"]
    assert review["fragment"]["content"] and review["review_open"] is False
    client.post(f"/v1/workspaces/{WS}/fragments/{fid}/votes", headers=as_("rhea"), json={
        "outcome": "promoted_to_advisory", "use_constraints": ["Advisory only."]})
    assert client.get("/v1/me/inbox", headers=as_("rhea")).json()["reviews"] == []
    [pending] = client.get("/v1/me/inbox", headers=as_("raj")).json()["reviews"]
    assert pending["proposal"]["use_constraints"] == ["Advisory only."]
    client.post(f"/v1/workspaces/{WS}/fragments/{fid}/votes", headers=as_("raj"),
                json={"outcome": "promoted_to_advisory"})
    [mine] = client.get("/v1/me/inbox", headers=as_("wendy")).json()["contributions"]
    assert mine["fragment_id"] == fid and mine["validation_state"] == "promoted_to_advisory"


def test_a_person_decides_an_escalation_and_the_agent_reads_it(server):
    client, as_, repo, recorder, app = server
    whisper = _observe(client, as_)
    client.post(f"/v1/workspaces/{WS}/whispers/{whisper['whisper_id']}/answer",
                headers=as_("wendy"), json={"response": "confirm", "consent": "granted"})
    fid = client.get("/v1/me/inbox", headers=as_("rhea")).json()["reviews"][0]["fragment_id"]
    for who in ("rhea", "raj"):
        client.post(f"/v1/workspaces/{WS}/fragments/{fid}/votes", headers=as_(who),
                    json={"outcome": "promoted_to_advisory"})
    task = client.post(f"/v1/workspaces/{WS}/retrieve", headers=as_("agent"),
                       json={"context": {**PUMP, "risk_class": "high"}}).json()["escalation_task_id"]
    [open_item] = client.get("/v1/me/inbox", headers=as_("raj")).json()["escalations"]
    assert open_item["task_id"] == task
    detail = f"/v1/workspaces/{WS}/escalations/{task}"
    assert client.get(detail, headers=as_("agent")).json()["decision"] is None
    assert client.get(detail, headers=as_("walt")).status_code == 404
    decide = f"{detail}/decision"
    body = {"outcome": "does_not_apply", "rationale": "High risk: follow SOP-17 strictly."}
    assert client.post(decide, headers=as_("rhea"), json=body).status_code == 403
    assert client.post(decide, headers=as_("raj"), json={"outcome": "applies", "rationale": ""}).status_code == 422
    decided = client.post(decide, headers=as_("raj"), json=body).json()
    assert decided["outcome"] == "does_not_apply" and decided["decided_by"] == PEOPLE["raj"]
    assert client.post(decide, headers=as_("raj"), json=body).status_code == 409
    seen = client.get(detail, headers=as_("agent")).json()
    assert seen["state"] == "completed" and seen["decision"]["rationale"] == body["rationale"]
    assert client.get("/v1/me/inbox", headers=as_("raj")).json()["escalations"] == []
    Dispatcher(repo, [recorder]).run_once()
    assert ("escalation.decided", PEOPLE["agent"]) in recorder.sent


def test_the_web_app_is_served_with_its_sign_in_settings(server):
    client, as_, repo, recorder, app = server
    page = client.get("/app")
    assert page.status_code == 200 and "<title>Metis</title>" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    config = client.get("/app/config").json()
    assert config == {"version": config["version"], "oidc": None, "api_keys": True,
                      "trusted_proxy": False}


def test_the_sweep_lapses_overdue_whispers(server):
    client, as_, repo, recorder, app = server
    whisper = _observe(client, as_)
    assert sweep(repo)["lapsed_whispers"] == 0
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    done = sweep(repo, later)
    assert done["lapsed_whispers"] == 1 and done["errors"] == 0
    assert client.get("/v1/me/inbox", headers=as_("wendy")).json()["whispers"] == []
    answer = client.post(f"/v1/workspaces/{WS}/whispers/{whisper['whisper_id']}/answer",
                         headers=as_("wendy"), json={"response": "confirm", "consent": "granted"})
    assert answer.status_code == 404


def test_background_work_starts_and_stops_with_the_server(tmp_path):
    _, digest = ApiKeyAuthenticator.generate()
    repo = SqlRepository(f"sqlite:///{tmp_path / 'b.db'}",
                         notifier=Notifier([Recorder(name="people")]))
    app = create_app(ServerSettings(sweep_interval_seconds=3600, dispatch_interval_seconds=3600),
                     repository=repo,
                     authenticator=AuthenticatorChain([ApiKeyAuthenticator(
                         [ApiKeyEntry(id="a", sha256=digest, uri="agent:a")])]))
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert app.state.sweeper._thread is not None and app.state.dispatcher._thread is not None
    assert app.state.sweeper._thread is None and app.state.dispatcher._thread is None
    repo.close()
