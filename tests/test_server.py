"""The multi-user server end to end: sign-in, roles, capture, votes, retrieval, and audit."""
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from metis.identity import ApiKeyAuthenticator, ApiKeyEntry, AuthenticatorChain, OIDCAuthenticator
from metis.server.app import create_app
from metis.server.settings import ServerSettings
from metis.storage.sql import SqlRepository

WS = "wsp_plant_a"
PEOPLE = {
    "admin": "human:admin@example.com",
    "wendy": "human:wendy@example.com",
    "walt": "human:walt@example.com",
    "rhea": "human:rhea@example.com",
    "raj": "human:raj@example.com",
    "rosa": "human:rosa@example.com",
    "agent": "agent:shift-assistant",
    "cmms": "agent:cmms-connector",
    "audrey": "human:audrey@example.com",
    "outsider": "human:olga@example.com",
}
PUMP = {"equipment_family": "centrifugal_pump", "operating_mode": "high_load"}
ASK = {**PUMP, "risk_class": "moderate"}  # an agent names its situation's risk class


@pytest.fixture()
def server(tmp_path):
    keys, entries = {}, []
    for name, uri in PEOPLE.items():
        key, digest = ApiKeyAuthenticator.generate()
        keys[name] = key
        roles = ("admin",) if name == "admin" else ("auditor",) if name == "audrey" else ()
        entries.append(ApiKeyEntry(id=name, sha256=digest, uri=uri, global_roles=roles))
    repo = SqlRepository(f"sqlite:///{tmp_path / 'server.db'}")
    app = create_app(ServerSettings(database_url="sqlite://"), repository=repo,
                     authenticator=AuthenticatorChain([ApiKeyAuthenticator(entries)]))
    client = TestClient(app)

    def as_(name):
        return {"Authorization": f"Bearer {keys[name]}"}

    members = [
        {"uri": PEOPLE["wendy"], "roles": ["worker"], "display_name": "Wendy"},
        {"uri": PEOPLE["walt"], "roles": ["worker"]},
        {"uri": PEOPLE["rhea"], "roles": ["reviewer"]},
        {"uri": PEOPLE["raj"], "roles": ["reviewer", "escalation"]},
        {"uri": PEOPLE["agent"], "roles": ["agent"]},
        {"uri": PEOPLE["cmms"], "roles": ["capture"]},
    ]
    created = client.post("/v1/workspaces", headers=as_("admin"),
                          json={"id": WS, "name": "Plant A", "site": "plant_a", "members": members})
    assert created.status_code == 201, created.text
    yield client, as_
    repo.close()


def _capture(client, as_):
    obs = client.post(f"/v1/workspaces/{WS}/observations", headers=as_("cmms"), json={
        "observation_id": "OBS-1", "work_as_done": "Ease back earlier on a dull sound.",
        "work_as_imagined": "Reduce load at the alarm.", "context": PUMP,
        "worker": PEOPLE["wendy"], "category": "K7_sensory"})
    assert obs.status_code == 201, obs.text
    whisper = obs.json()
    assert whisper["worker"] == PEOPLE["wendy"] and whisper["submitted_by"] == PEOPLE["cmms"]
    answer = client.post(f"/v1/workspaces/{WS}/whispers/{whisper['whisper_id']}/answer",
                         headers=as_("wendy"), json={"response": "confirm", "consent": "granted"})
    assert answer.status_code == 200, answer.text
    return answer.json()["fragment"]["fragment_id"]


def _promote(client, as_, fid):
    first = client.post(f"/v1/workspaces/{WS}/fragments/{fid}/votes", headers=as_("rhea"),
                        json={"outcome": "promoted_to_advisory", "summary": "clear cue"})
    assert first.json()["status"] == "pending", first.text
    second = client.post(f"/v1/workspaces/{WS}/fragments/{fid}/votes", headers=as_("raj"),
                         json={"outcome": "promoted_to_advisory"})
    assert second.json()["status"] == "decided", second.text
    return second.json()


def test_health_and_sign_in(server):
    client, as_ = server
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").status_code == 200
    unauthenticated = client.get("/v1/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["WWW-Authenticate"] == "Bearer"
    assert client.get("/v1/me", headers={"Authorization": "Bearer metis_wrong"}).status_code == 401
    me = client.get("/v1/me", headers=as_("raj")).json()
    assert me["uri"] == PEOPLE["raj"] and me["sign_in"] == "api_key"
    assert me["workspaces"] == [{"id": WS, "name": "Plant A", "roles": ["reviewer", "escalation"]}]
    assert client.get("/v1/workspaces", headers=as_("outsider")).json() == []
    hidden = client.get(f"/v1/workspaces/{WS}", headers=as_("outsider"))
    missing = client.get("/v1/workspaces/wsp_nowhere", headers=as_("outsider"))
    assert hidden.status_code == missing.status_code == 404  # an outsider cannot tell them apart
    assert hidden.json()["detail"].replace(WS, "?") == missing.json()["detail"].replace(
        "wsp_nowhere", "?")
    assert client.get(f"/v1/workspaces/{WS}", headers=as_("audrey")).status_code == 200


def test_only_global_admins_create_workspaces(server):
    client, as_ = server
    body = {"id": "wsp_plant_b", "name": "Plant B"}
    assert client.post("/v1/workspaces", headers=as_("rhea"), json=body).status_code == 403
    assert client.post("/v1/workspaces", headers=as_("admin"), json=body).status_code == 201
    assert client.post("/v1/workspaces", headers=as_("admin"), json=body).status_code == 409
    bad = client.post("/v1/workspaces", headers=as_("admin"), json={"id": "Plant C", "name": "x"})
    assert bad.status_code == 422


def test_capture_is_answered_only_by_the_worker_asked(server):
    client, as_ = server
    # A worker may report only their own work; a reviewer cannot report.
    for who, worker in (("walt", PEOPLE["wendy"]), ("rhea", PEOPLE["wendy"])):
        refused = client.post(f"/v1/workspaces/{WS}/observations", headers=as_(who), json={
            "observation_id": "X", "work_as_done": "x", "context": PUMP, "worker": worker})
        assert refused.status_code == 403
    obs = client.post(f"/v1/workspaces/{WS}/observations", headers=as_("cmms"), json={
        "observation_id": "OBS-1", "work_as_done": "Ease back earlier.", "context": PUMP,
        "worker": PEOPLE["wendy"]}).json()
    assert [w["whisper_id"] for w in client.get(f"/v1/workspaces/{WS}/whispers",
                                                headers=as_("wendy")).json()] == [obs["whisper_id"]]
    assert client.get(f"/v1/workspaces/{WS}/whispers", headers=as_("walt")).json() == []
    assert client.get(f"/v1/workspaces/{WS}/whispers", headers=as_("rhea")).status_code == 403
    url = f"/v1/workspaces/{WS}/whispers/{obs['whisper_id']}/answer"
    body = {"response": "confirm", "consent": "granted"}
    assert client.post(url, headers=as_("walt"), json=body).status_code == 403
    assert client.post(url, headers=as_("agent"), json=body).status_code == 403
    assert client.post(url, headers=as_("wendy"), json=body).json()["stored"] is True
    assert client.post(url, headers=as_("wendy"), json=body).status_code == 404


def test_votes_complete_a_promotion_at_quorum(server):
    client, as_ = server
    fid = _capture(client, as_)
    queue = client.get(f"/v1/workspaces/{WS}/reviews", headers=as_("rhea")).json()
    assert [q["fragment_id"] for q in queue] == [fid] and queue[0]["review_open"] is False
    vote = f"/v1/workspaces/{WS}/fragments/{fid}/votes"
    assert client.post(vote, headers=as_("agent"), json={"outcome": "promoted_to_advisory"}).status_code == 403
    assert client.post(vote, headers=as_("wendy"), json={"outcome": "promoted_to_advisory"}).status_code == 403
    blocked = client.post(vote, headers=as_("raj"), json={"outcome": "promoted_to_controlled"})
    assert blocked.status_code == 403 and "change-control" in blocked.json()["detail"]
    constraints = ["Present as an advisory cue only.", "Confirm the sound with the operator."]
    first = client.post(vote, headers=as_("rhea"), json={
        "outcome": "promoted_to_advisory", "use_constraints": constraints}).json()
    assert first["status"] == "pending" and first["approvals"] == [PEOPLE["rhea"]]
    queue = client.get(f"/v1/workspaces/{WS}/reviews", headers=as_("raj")).json()
    assert queue[0]["review_open"] and queue[0]["approvals"][0]["reviewer"] == PEOPLE["rhea"]
    assert queue[0]["proposal"]["use_constraints"] == constraints
    assert client.post(vote, headers=as_("rhea"), json={"outcome": "promoted_to_advisory"}).status_code == 409
    disagreeing = client.post(vote, headers=as_("raj"), json={
        "outcome": "promoted_to_controlled", "change_control": {"ticket": "CC-9"}})
    assert disagreeing.status_code == 409
    other_terms = client.post(vote, headers=as_("raj"), json={
        "outcome": "promoted_to_advisory", "use_constraints": ["Act on it."]})
    assert other_terms.status_code == 409
    decided = client.post(vote, headers=as_("raj"), json={"outcome": "promoted_to_advisory"}).json()
    assert decided["status"] == "decided" and decided["authority_layer"] == "advisory"
    assert decided["decided_by"] == [PEOPLE["rhea"], PEOPLE["raj"]] and decided["memory_id"]
    frag = client.get(f"/v1/workspaces/{WS}/fragments/{fid}", headers=as_("rhea")).json()
    assert frag["use_constraints"] == constraints and frag["proposal"] is None


def test_agents_receive_only_governed_guidance(server):
    client, as_ = server
    fid = _capture(client, as_)
    retrieve = f"/v1/workspaces/{WS}/retrieve"
    early = client.post(retrieve, headers=as_("agent"), json={"context": ASK}).json()
    assert early["guidance"] == [] and early["not_yet_authorised"] == 1
    assert client.post(retrieve, headers=as_("rhea"), json={"context": ASK}).status_code == 403
    _promote(client, as_, fid)
    guided = client.post(retrieve, headers=as_("agent"), json={"context": ASK}).json()
    assert [g["fragment_id"] for g in guided["guidance"]] == [fid]
    assert guided["guidance"][0]["use_constraints"]
    risky = client.post(retrieve, headers=as_("agent"),
                        json={"context": {**PUMP, "risk_class": "high"}}).json()
    assert risky["required_human_actions"] and risky["escalation_task_id"]
    open_items = client.get(f"/v1/workspaces/{WS}/escalations", headers=as_("raj")).json()
    assert [e["task_id"] for e in open_items] == [risky["escalation_task_id"]]
    assert open_items[0]["requested_by"] == PEOPLE["agent"]
    assert client.get(f"/v1/workspaces/{WS}/escalations", headers=as_("wendy")).status_code == 403
    memory = client.get(f"/v1/workspaces/{WS}/memory", headers=as_("agent")).json()
    assert [m["fragment_id"] for m in memory] == [fid] and "content" not in memory[0]
    context = client.post(f"/v1/workspaces/{WS}/agent-context", headers=as_("agent"),
                          json={"task": "tsk_shift", "context": ASK}).json()
    assert [t["fragment_id"] for t in context["tacit"]] == [fid]


def test_fragment_visibility_follows_roles(server):
    client, as_ = server
    fid = _capture(client, as_)
    url = f"/v1/workspaces/{WS}/fragments"
    assert [f["fragment_id"] for f in client.get(url, headers=as_("wendy")).json()] == [fid]
    assert client.get(url, headers=as_("walt")).json() == []
    assert client.get(f"{url}/{fid}", headers=as_("walt")).status_code == 404
    assert client.get(url, headers=as_("agent")).status_code == 403
    assert client.get(f"{url}/{fid}", headers=as_("rhea")).json()["fragment_id"] == fid
    assert client.get(f"{url}/{fid}", headers=as_("audrey")).status_code == 200


def test_workers_contest_and_withdraw_their_own_fragments(server):
    client, as_ = server
    fid = _capture(client, as_)
    _promote(client, as_, fid)
    base = f"/v1/workspaces/{WS}/fragments/{fid}"
    contest = {"action": "challenge", "rationale": "the cue changed after the overhaul"}
    assert client.post(f"{base}/contest", headers=as_("walt"), json=contest).status_code == 404
    contested = client.post(f"{base}/contest", headers=as_("wendy"), json=contest).json()
    assert contested["recorded"] and contested["mission_group_task"]
    assert client.post(f"{base}/withdraw", headers=as_("rhea"), json={}).status_code == 403
    assert client.post(f"{base}/withdraw", headers=as_("wendy"), json={"note": "mine"}).json()["withdrawn"]
    after = client.post(f"/v1/workspaces/{WS}/retrieve", headers=as_("agent"), json={"context": ASK}).json()
    assert after["guidance"] == []


def test_reviewers_retire_and_reopen(server):
    client, as_ = server
    fid = _capture(client, as_)
    _promote(client, as_, fid)
    base = f"/v1/workspaces/{WS}/fragments/{fid}"
    assert client.post(f"{base}/reviews", headers=as_("wendy"), json={}).status_code == 403
    opened = client.post(f"{base}/reviews", headers=as_("rhea"), json={"reason": "renewal"}).json()
    assert opened["review_open"] and opened["review_task"]
    assert client.post(f"{base}/retire", headers=as_("agent"), json={}).status_code == 403
    retired = client.post(f"{base}/retire", headers=as_("raj"), json={"reason": "drift"}).json()
    assert retired["retired"]


def test_admins_manage_members_and_every_change_is_recorded(server):
    client, as_ = server
    url = f"/v1/workspaces/{WS}/members"
    rosa = {"uri": PEOPLE["rosa"], "roles": ["reviewer"], "reason": "joined quality"}
    assert client.put(url, headers=as_("rhea"), json=rosa).status_code == 403
    assert client.put(url, headers=as_("admin"), json=rosa).json()["roles"] == ["reviewer"]
    bad = client.put(url, headers=as_("admin"), json={"uri": PEOPLE["agent"], "roles": ["reviewer"]})
    assert bad.status_code == 422
    listed = {m["uri"]: m["roles"] for m in client.get(url, headers=as_("rhea")).json()}
    assert listed[PEOPLE["rosa"]] == ["reviewer"]
    assert client.get(url, headers=as_("wendy")).status_code == 403
    removed = client.put(url, headers=as_("admin"), json={"uri": PEOPLE["rosa"], "roles": []}).json()
    assert removed["removed"] is True
    entries = client.get(f"/v1/workspaces/{WS}/audit", headers=as_("audrey"),
                         params={"limit": 1000}).json()["entries"]
    kinds = [e["envelope"]["params"].get("output", {}).get("kind") for e in entries
             if e["method_or_type"] == "task.complete"]
    assert kinds.count("tacit.membership_record") == 6 + 2


def test_auditors_verify_and_export_the_chain(server):
    client, as_ = server
    fid = _capture(client, as_)
    _promote(client, as_, fid)
    assert client.get(f"/v1/workspaces/{WS}/audit/verify", headers=as_("rhea")).status_code == 403
    verified = client.get(f"/v1/workspaces/{WS}/audit/verify", headers=as_("audrey")).json()
    assert verified["verified"] and verified["ledger_agrees"]
    assert verified["entries"] == verified["ledger_entries"]
    export = client.get(f"/v1/workspaces/{WS}/audit/export", headers=as_("audrey"))
    lines = [json.loads(line) for line in export.text.splitlines()]
    assert len(lines) == verified["entries"] and lines[0]["seq"] == 0
    assert export.headers["content-type"].startswith("application/x-ndjson")


def test_oidc_sign_in(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "k1"})
    issuer = "https://idp.example.com/realms/metis"
    oidc = OIDCAuthenticator(issuer=issuer, audience="metis-api", jwks={"keys": [jwk]},
                             roles_claim="realm_access.roles")
    repo = SqlRepository(f"sqlite:///{tmp_path / 'server.db'}")
    client = TestClient(create_app(ServerSettings(), repository=repo,
                                   authenticator=AuthenticatorChain([oidc])))
    now = int(time.time())
    token = jwt.encode({"iss": issuer, "aud": "metis-api", "sub": "u1", "iat": now,
                        "exp": now + 60, "email": "ana@example.com",
                        "realm_access": {"roles": ["metis-admin"]}},
                       key, algorithm="RS256", headers={"kid": "k1"})
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["uri"] == "human:ana@example.com" and me["global_roles"] == ["admin"]
    created = client.post("/v1/workspaces", headers={"Authorization": f"Bearer {token}"},
                          json={"id": "wsp_oidc", "name": "OIDC"})
    assert created.status_code == 201
    repo.close()


def test_settings_from_the_environment(tmp_path):
    keys = tmp_path / "keys.yaml"
    _, digest = ApiKeyAuthenticator.generate()
    ApiKeyAuthenticator.write_file(keys, [ApiKeyEntry(id="a", sha256=digest, uri="agent:a")])
    settings = ServerSettings.from_env({
        "METIS_DATABASE_URL": "postgresql://metis:pw@db/metis",
        "METIS_API_KEYS_FILE": str(keys), "METIS_ADMINS": "human:a@example.com, human:b@example.com",
        "METIS_WHISPER_DEADLINE_HOURS": "48", "METIS_USE_LIVE_MODEL": "true"})
    assert settings.admins == ["human:a@example.com", "human:b@example.com"]
    assert settings.whisper_deadline_ms == 48 * 3600 * 1000 and settings.use_live_model
    assert len(settings.authenticator().authenticators) == 1
    with pytest.raises(ValueError):
        ServerSettings.from_env({}).authenticator()
    with pytest.raises(ValueError):
        ServerSettings.from_env({"METIS_OIDC_ISSUER": "https://idp"}).authenticators()


def test_requests_are_bounded_and_forms_are_refused(server, tmp_path):
    client, as_ = server
    huge = b"x" * (4 * 1024 * 1024 + 1)
    assert client.post("/v1/workspaces", content=huge,
                       headers={"Content-Type": "application/json"}).status_code == 413
    # Without credentials a browser adds itself, a change needs a JSON body: a cross-site form
    # cannot send one.
    form = client.post(f"/v1/workspaces/{WS}/fragments/TF-00001/withdraw",
                       headers={"Content-Type": "text/plain"}, content=b"")
    assert form.status_code == 415
    long = client.post(f"/v1/workspaces/{WS}/observations", headers=as_("cmms"), json={
        "observation_id": "OBS-L", "work_as_done": "x" * 5000, "context": PUMP,
        "worker": PEOPLE["wendy"]})
    assert long.status_code == 422
    deep = client.post(f"/v1/workspaces/{WS}/retrieve", headers=as_("agent"),
                       json={"context": {**ASK, "equipment_family": "x" * 300}})
    assert deep.status_code == 422 and "limit" in deep.json()["detail"]


def test_the_web_app_runs_only_its_own_script(server):
    client, as_ = server
    page = client.get("/app")
    policy = page.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in policy.split("style-src")[0] and "'sha256-" in policy
    assert "connect-src 'self'" in policy and "*" not in policy
    assert page.headers["X-Frame-Options"] == "DENY"
    assert client.get("/docs").status_code == 404  # the API browser is off unless asked for


def test_a_repeated_observation_returns_its_whisper(server):
    client, as_ = server
    body = {"observation_id": "OBS-R", "work_as_done": "Ease back earlier.", "context": PUMP,
            "worker": PEOPLE["wendy"]}
    url = f"/v1/workspaces/{WS}/observations"
    first = client.post(url, headers=as_("cmms"), json=body).json()
    again = client.post(url, headers=as_("cmms"), json=body)
    assert again.status_code in (200, 201) and again.json()["whisper_id"] == first["whisper_id"]
    other = client.post(url, headers=as_("cmms"), json={**body, "work_as_done": "Something else."})
    assert other.status_code == 409
    inbox = client.get("/v1/me/inbox", headers=as_("wendy")).json()["whispers"]
    assert [w["whisper_id"] for w in inbox] == [first["whisper_id"]]


def test_busy_workspaces_and_unreachable_providers_answer_503(server, monkeypatch):
    client, as_ = server
    from metis.identity import IdentityProviderUnavailable
    from metis.storage.repository import WorkspaceBusy

    def busy(*a, **kw):
        raise WorkspaceBusy("wsp_plant_a is busy; try again shortly.")
    monkeypatch.setattr(SqlRepository, "write", busy)
    response = client.post(f"/v1/workspaces/{WS}/retrieve", headers=as_("agent"),
                           json={"context": ASK})
    assert response.status_code == 503 and response.headers["Retry-After"] == "2"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]

    def down(headers):
        raise IdentityProviderUnavailable("The identity provider is unreachable; try again shortly.")
    monkeypatch.setattr(client.app.state.auth, "authenticate", down)
    assert client.get("/v1/me", headers=as_("agent")).status_code == 503


def test_half_configured_chat_integrations_are_refused():
    with pytest.raises(ValueError, match="SIGNING_SECRET"):
        create_app(ServerSettings(slack_bot_token="xoxb-1"), repository=object(),
                   authenticator=object())
    with pytest.raises(ValueError, match="tenants"):
        create_app(ServerSettings(teams_app_id="a", teams_app_password="p"), repository=object(),
                   authenticator=object())


def test_only_the_contributor_replaces_a_fragment_sent_back(server):
    client, as_ = server
    fid = _capture(client, as_)
    sent_back = client.post(f"/v1/workspaces/{WS}/fragments/{fid}/votes", headers=as_("rhea"),
                            json={"outcome": "re_elicit", "summary": "say more about the sound"})
    assert sent_back.status_code == 200, sent_back.text
    body = {"observation_id": "OBS-2", "work_as_done": "Ease back when the note dulls.",
            "context": PUMP, "supersedes": fid}
    url = f"/v1/workspaces/{WS}/observations"
    assert client.post(url, headers=as_("walt"), json=body).status_code == 403
    assert client.post(url, headers=as_("wendy"), json=body).status_code == 201


def test_the_live_model_drafts_before_the_workspace_is_locked(server, monkeypatch):
    client, as_ = server
    from metis.models.ollama_client import OllamaClient

    seen = {"writing": False, "calls": []}
    real = SqlRepository._write_once

    def tracking(self, workspace_id, fn):
        seen["writing"] = True
        try:
            return real(self, workspace_id, fn)
        finally:
            seen["writing"] = False

    def respond(purpose, prompt):
        seen["calls"].append((purpose, seen["writing"]))
        return json.dumps({"category": "K7_sensory", "question": "What did you hear?",
                           "summary": "Eases back when the pump sounds dull."})
    monkeypatch.setattr(SqlRepository, "_write_once", tracking)
    monkeypatch.setattr(SqlRepository, "model_client", lambda self: OllamaClient(responder=respond))
    whisper = client.post(f"/v1/workspaces/{WS}/observations", headers=as_("cmms"), json={
        "observation_id": "OBS-M", "work_as_done": "Ease back earlier on a dull sound.",
        "context": PUMP, "worker": PEOPLE["wendy"]}).json()
    answer = client.post(f"/v1/workspaces/{WS}/whispers/{whisper['whisper_id']}/answer",
                         headers=as_("wendy"), json={"response": "confirm", "consent": "granted"})
    assert answer.status_code == 200, answer.text
    purposes = {purpose for purpose, _ in seen["calls"]}
    assert {"classify_fragment", "draft_whisper", "summarise_confirmation"} <= purposes
    assert not any(writing for _, writing in seen["calls"])  # no model call holds the writer


def test_operators_read_counts_never_content(server):
    client, as_ = server
    assert client.get("/metrics", headers=as_("wendy")).status_code == 403
    status = client.get("/v1/admin/status", headers=as_("audrey")).json()
    assert status["workspaces"] == 1 and status["schema_version"] == 4
    assert set(status["outbox"]) == {"pending", "sending", "delivered", "failed"}
    metrics = client.get("/metrics", headers=as_("audrey")).text
    assert "metis_workspaces 1" in metrics and 'metis_outbox_notifications{status="failed"}' in metrics


def test_changes_need_json_whatever_the_credentials(server):
    client, as_ = server
    url = f"/v1/workspaces/{WS}/fragments/TF-00001/withdraw"
    for headers in ({**as_("wendy"), "Content-Type": "text/plain"},
                    {"Authorization": "", "Content-Type": "application/x-www-form-urlencoded"},
                    {"Authorization": "Basic d2VuZHk6cHc=", "Content-Type": "text/plain"}):
        assert client.post(url, headers=headers, content=b"note=x").status_code == 415


def test_a_body_of_unknown_length_is_bounded_too(server):
    client, as_ = server

    def chunks():
        for _ in range(5):
            yield b"x" * (1024 * 1024)
    response = client.post(f"/v1/workspaces/{WS}/observations", content=chunks(),
                           headers={**as_("cmms"), "Content-Type": "application/json"})
    assert response.status_code == 413


def test_a_refused_ingest_asks_the_model_nothing(server, monkeypatch, tmp_path):
    client, as_ = server
    from metis.connectors.mapping import SourceMapping
    from metis.models.ollama_client import OllamaClient
    from metis.server import operations as ops

    calls = []
    monkeypatch.setattr(SqlRepository, "model_client", lambda self: OllamaClient(
        responder=lambda purpose, prompt: calls.append(purpose) or "{}"))
    mapping = SourceMapping(name="cmms", id="$.id", worker="$.w", work_as_done="$.d")
    records = [{"id": i, "w": PEOPLE["wendy"], "d": "Eased back."} for i in range(5)]
    repo = client.app.state.repo
    from metis.identity import Principal
    from metis.server.access import ScopedRepository

    wendy = Principal(uri=PEOPLE["wendy"], subject="s", method="api_key")  # no capture role
    with pytest.raises(PermissionError):
        ops.ingest(ScopedRepository(repo, wendy), wendy, WS, mapping, records)
    assert calls == []
    cmms = Principal(uri=PEOPLE["cmms"], subject="s", method="api_key")
    ops.ingest(ScopedRepository(repo, cmms), cmms, WS, mapping, records[:2])
    asked = len(calls)
    assert asked > 0
    again = ops.ingest(ScopedRepository(repo, cmms), cmms, WS, mapping, records[:2])
    assert again["duplicates"] == ["cmms:0", "cmms:1"] and len(calls) == asked  # nothing new
