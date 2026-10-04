"""Whispers in Slack and Microsoft Teams, answered in place and recorded as the worker."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from metis.conditions.context import TacitContext
from metis.connectors.slack import (
    SlackAPI,
    SlackInteractions,
    SlackWhisperChannel,
    verify_signature,
)
from metis.connectors.teams import (
    ISSUER,
    BotConnector,
    TeamsBot,
    TeamsBotAuth,
    TeamsWhisperChannel,
)
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.governance.membership import Member, Role
from metis.identity import ApiKeyAuthenticator, ApiKeyEntry, AuthenticatorChain
from metis.notify import Notification
from metis.server.app import create_app
from metis.server.settings import ServerSettings
from metis.storage.repository import WorkspaceSettings
from metis.storage.sql import SqlRepository

WS = "wsp_plant_a"
WENDY, WALT = "human:wendy@example.com", "human:walt@example.com"
PUMP = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load")
SECRET = "slack-signing-secret"


@pytest.fixture()
def repo(tmp_path):
    repository = SqlRepository(f"sqlite:///{tmp_path / 'chat.db'}")
    repository.create(WorkspaceSettings(id=WS, name="Plant A", members=[
        Member(uri=WENDY, roles=[Role.worker]), Member(uri=WALT, roles=[Role.worker]),
        Member(uri="agent:cmms-connector", roles=[Role.capture])]), by="human:admin@example.com")
    yield repository
    repository.close()


def _whisper(repo) -> str:
    return repo.write(WS, lambda e: e.begin_capture(
        {"observation_id": "WO-1", "work_as_done": "Eased back earlier.", "context": PUMP},
        consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=WENDY,
        submitted_by="agent:cmms-connector", category="K7_sensory", conditions=PUMP).whisper_id)


def _note(whisper_id) -> Notification:
    return Notification(event="whisper.asked", workspace_id=WS, workspace_name="Plant A",
                        recipients=[WENDY], subject={"whisper_id": whisper_id,
                                                     "question": "What cue made you pause?",
                                                     "observation": "Eased back earlier."})


def _stored(repo, whisper_id):
    return repo.read(WS, lambda e: (whisper_id in e.pending_captures,
                                    [f.content for f in e.fragments.all()]))


# ---- Slack -------------------------------------------------------------------------------
class FakeSlack(SlackAPI):
    def __init__(self):
        super().__init__("xoxb-test")
        self.calls, self.responses = [], []
        self.users = {"U_WENDY": "wendy@example.com", "U_WALT": "walt@example.com"}

    def call(self, method, **payload):
        self.calls.append((method, payload))
        return {"ok": True}

    def get(self, method, **params):
        if method == "users.lookupByEmail":
            uid = next(u for u, e in self.users.items() if e == params["email"])
            return {"ok": True, "user": {"id": uid}}
        return {"ok": True, "user": {"profile": {"email": self.users[params["user"]]}}}

    def post_response(self, url, message):
        self.responses.append(message)


def _signed(payload: dict, *, secret=SECRET, timestamp=None):
    body = urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(timestamp or time.time()))
    sig = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}, body


def _click(user, whisper_id, response, consent):
    return {"type": "block_actions", "user": {"id": user}, "trigger_id": "trig-1",
            "response_url": "https://hooks.slack.com/actions/x",
            "actions": [{"action_id": f"answer_{response}",
                         "value": json.dumps({"w": WS, "id": whisper_id, "r": response})}],
            "state": {"values": {"consent": {"consent": {
                "selected_options": [{"value": "granted"}] if consent else []}}}}}


def test_slack_signatures():
    headers, body = _signed({"type": "x"})
    assert verify_signature(SECRET, headers, body)
    assert not verify_signature("other", headers, body)
    old_headers, old_body = _signed({"type": "x"}, timestamp=time.time() - 3600)
    assert not verify_signature(SECRET, old_headers, old_body)


def test_a_whisper_reaches_the_worker_in_slack_and_the_answer_is_recorded(repo):
    whisper = _whisper(repo)
    slack = FakeSlack()
    SlackWhisperChannel(name="slack", api=slack).deliver(_note(whisper), WENDY, 1)
    method, message = slack.calls[-1]
    assert method == "chat.postMessage" and message["channel"] == "U_WENDY"
    buttons = message["blocks"][-1]["elements"]
    assert json.loads(buttons[0]["value"]) == {"w": WS, "id": whisper, "r": "confirm"}

    bot = SlackInteractions(repo, slack, SECRET)
    status, _ = bot.handle(*_signed(_click("U_WALT", whisper, "confirm", True)))
    assert status == 200 and slack.responses[-1]["text"] == "This question is for someone else."
    bot.handle(*_signed(_click("U_WENDY", whisper, "confirm", False)))
    assert slack.responses[-1]["response_type"] == "ephemeral"
    assert _stored(repo, whisper)[0] is True  # nothing recorded yet
    bot.handle(*_signed(_click("U_WENDY", whisper, "confirm", True)))
    assert slack.responses[-1]["replace_original"] is True
    pending, contents = _stored(repo, whisper)
    assert pending is False and len(contents) == 1
    headers, body = _signed(_click("U_WENDY", whisper, "confirm", True), secret="forged")
    assert bot.handle(headers, body)[0] == 401


def test_a_slack_correction_opens_a_form(repo):
    whisper = _whisper(repo)
    slack = FakeSlack()
    bot = SlackInteractions(repo, slack, SECRET)
    bot.handle(*_signed(_click("U_WENDY", whisper, "correct", True)))
    method, call = slack.calls[-1]
    assert method == "views.open" and call["view"]["callback_id"] == "metis_correct"
    submission = {"type": "view_submission", "user": {"id": "U_WENDY"}, "view": {
        "callback_id": "metis_correct", "private_metadata": call["view"]["private_metadata"],
        "state": {"values": {"text": {"text": {"value": "I listen for a dull note at high load."}},
                             "consent": {"consent": {"selected_options": [{"value": "granted"}]}}}}}}
    status, reply = bot.handle(*_signed(submission))
    assert status == 200 and reply == {"response_action": "clear"}
    assert "dull note" in _stored(repo, whisper)[1][0]


def test_the_slack_endpoint_on_the_server(repo, tmp_path):
    _, digest = ApiKeyAuthenticator.generate()
    app = create_app(ServerSettings(slack_bot_token="xoxb-test", slack_signing_secret=SECRET),
                     repository=repo, authenticator=AuthenticatorChain([ApiKeyAuthenticator(
                         [ApiKeyEntry(id="a", sha256=digest, uri="agent:a")])]))
    app.state.slack.api = FakeSlack()
    whisper = _whisper(repo)
    headers, body = _signed(_click("U_WENDY", whisper, "confirm", True))
    client = TestClient(app)
    response = client.post("/integrations/slack/interactions", content=body,
                           headers={**headers, "Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 200 and _stored(repo, whisper)[0] is False
    assert client.post("/integrations/teams/messages", json={}).status_code == 404


# ---- Teams -------------------------------------------------------------------------------
APP_ID = "00000000-0000-0000-0000-00000000b0t1"
SERVICE = "https://smba.trafficmanager.net/emea/"


@pytest.fixture(scope="module")
def bot_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _bot_token(key, **claims):
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": APP_ID, "iat": now, "exp": now + 300, "serviceurl": SERVICE,
               **claims}
    return "Bearer " + jwt.encode(payload, key, algorithm="RS256")


class FakeConnector:
    def __init__(self):
        self.sent, self.updated = [], []
        self.members = {"29:wendy": {"email": "Wendy@Example.com", "aadObjectId": "aad-wendy"},
                        "29:walt": {"email": "walt@example.com", "aadObjectId": "aad-walt"},
                        "29:impostor": {"email": "wendy@example.com", "aadObjectId": "aad-evil"}}
        self.lookups = []

    def member(self, service_url, conversation_id, member_id):
        self.lookups.append(member_id)
        return self.members[member_id]

    def send(self, service_url, conversation_id, activity):
        self.sent.append((conversation_id, activity))
        return {"id": "act-1"}

    def update(self, service_url, conversation_id, activity_id, activity):
        self.updated.append((activity_id, activity))
        return {}


def _activity(kind, sender="29:wendy", tenant="t1", **extra):
    return {"type": kind, "channelId": "msteams", "serviceUrl": SERVICE, "from": {"id": sender},
            "recipient": {"id": "28:bot"},
            "conversation": {"id": f"a:{sender}", "conversationType": "personal",
                             "tenantId": tenant},
            **extra}


def _bot(repo, bot_key, connector):
    auth = TeamsBotAuth(APP_ID, key_resolver=lambda t: (bot_key.public_key(), ["msteams"]))
    return TeamsBot(repo, auth, connector, tenants=["t1"])


def test_teams_tokens_are_verified(bot_key):
    auth = TeamsBotAuth(APP_ID, key_resolver=lambda token: (bot_key.public_key(), ["msteams"]))
    assert auth.verify(_bot_token(bot_key), SERVICE, channel_id="msteams")["aud"] == APP_ID
    from metis.identity import AuthenticationError

    no_service_url = "Bearer " + jwt.encode(
        {"iss": ISSUER, "aud": APP_ID, "exp": int(time.time()) + 300}, bot_key, algorithm="RS256")
    no_expiry = "Bearer " + jwt.encode(
        {"iss": ISSUER, "aud": APP_ID, "serviceurl": SERVICE}, bot_key, algorithm="RS256")
    for bad in (_bot_token(bot_key, aud="someone-else"), _bot_token(bot_key, iss="https://evil"),
                _bot_token(bot_key, serviceurl="https://elsewhere/"), no_service_url, no_expiry):
        with pytest.raises(AuthenticationError):
            auth.verify(bad, SERVICE, channel_id="msteams")
    with pytest.raises(AuthenticationError):
        auth.verify(None, SERVICE)
    with pytest.raises(AuthenticationError, match="not endorsed"):
        auth.verify(_bot_token(bot_key), SERVICE, channel_id="skype")


def test_a_whisper_reaches_the_worker_in_teams_and_the_answer_is_recorded(repo, bot_key):
    connector = FakeConnector()
    bot = _bot(repo, bot_key, connector)
    headers = {"Authorization": _bot_token(bot_key)}
    install = _activity("conversationUpdate", membersAdded=[{"id": "29:wendy"}, {"id": "28:bot"}])
    assert bot.handle(headers, install) == (200, None)
    where = repo.chat_identity("teams", WENDY)
    assert where["conversation_id"] == "a:29:wendy" and where["service_url"] == SERVICE

    whisper = _whisper(repo)
    channel = TeamsWhisperChannel(name="teams", connector=connector, directory=repo.chat_identity)
    channel.deliver(_note(whisper), WENDY, 1)
    card = connector.sent[-1][1]["attachments"][0]["content"]
    submit = card["actions"][0]
    assert submit["data"] == {"metis": "answer", "w": WS, "id": whisper, "r": "confirm"}
    with pytest.raises(LookupError):
        channel.deliver(_note(whisper), WALT, 2)

    declined = _activity("message", value={**submit["data"], "consent": "declined"}, replyToId="act-1")
    bot.handle(headers, declined)
    notice = connector.sent[-1][1]["attachments"][0]["content"]["body"][0]
    assert "consent" in notice["inlines"][0]["text"]
    assert _stored(repo, whisper)[0] is True
    answered = _activity("message", value={**submit["data"], "consent": "granted"}, replyToId="act-1")
    bot.handle(headers, answered)
    assert connector.updated[-1][0] == "act-1"
    assert _stored(repo, whisper)[0] is False and len(_stored(repo, whisper)[1]) == 1
    assert bot.handle({"Authorization": "Bearer forged"}, answered)[0] == 401


def test_the_bot_connector_uses_its_own_token():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers.get("authorization")))
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        return httpx.Response(200, json={"id": "act-9"})

    connector = BotConnector(APP_ID, "secret", tenant_id="t1",
                             http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert connector.send(SERVICE, "a:29:wendy", {"type": "message"}) == {"id": "act-9"}
    assert seen[0][1] == "https://login.microsoftonline.com/t1/oauth2/v2.0/token"
    assert seen[1] == ("POST", SERVICE + "v3/conversations/a:29:wendy/activities", "Bearer bot-token")


def test_teams_refuses_other_tenants_channels_and_services(repo, bot_key):
    connector = FakeConnector()
    bot = _bot(repo, bot_key, connector)
    headers = {"Authorization": _bot_token(bot_key)}
    install = _activity("conversationUpdate", tenant="evil-tenant",
                        membersAdded=[{"id": "29:wendy"}])
    assert bot.handle(headers, install)[0] == 403 and connector.lookups == []
    assert bot.handle(headers, {**_activity("message"), "channelId": "skype"})[0] in (401, 403)
    assert bot.handle(headers, ["not", "an", "activity"])[0] == 400
    elsewhere = {**_activity("message"), "serviceUrl": "https://evil.example/"}
    token = {"Authorization": _bot_token(bot_key, serviceurl="https://evil.example/")}
    assert bot.handle(token, elsewhere)[0] == 403 and connector.lookups == []
    with pytest.raises(ValueError, match="not a Bot Framework service host"):
        BotConnector(APP_ID, "secret", tenant_id="t1").send("https://evil.example/", "c", {})
    with pytest.raises(ValueError, match="tenants"):
        TeamsBot(repo, TeamsBotAuth(APP_ID), connector, tenants=[])


def test_a_teams_identity_is_bound_to_one_account(repo, bot_key):
    connector = FakeConnector()
    bot = _bot(repo, bot_key, connector)
    headers = {"Authorization": _bot_token(bot_key)}
    bot.handle(headers, _activity("conversationUpdate", membersAdded=[{"id": "29:wendy"}]))
    assert repo.chat_identity("teams", WENDY)["external_id"] == "29:wendy"
    impostor = _activity("conversationUpdate", sender="29:impostor",
                         membersAdded=[{"id": "29:impostor"}])
    bot.handle(headers, impostor)  # same email, another Entra account: not rebound
    assert repo.chat_identity("teams", WENDY)["external_id"] == "29:wendy"
    removed = _activity("installationUpdate", action="remove")
    bot.handle(headers, removed)
    assert repo.chat_identity("teams", WENDY) is None


def test_slack_text_is_escaped_and_bad_requests_are_refused(repo):
    from metis.connectors.slack import whisper_blocks

    hostile = Notification(event="whisper.asked", workspace_id=WS, workspace_name="Plant A",
                           recipients=[WENDY], subject={
                               "whisper_id": "w1", "question": "<!channel> please",
                               "observation": "<https://evil.example|Open Metis>"})
    blocks = whisper_blocks(hostile)
    rendered = json.dumps(blocks)
    assert "<!channel>" not in rendered and "<https://evil" not in rendered
    option = blocks[-2]["elements"][0]["options"][0]
    assert len(option["text"]["text"]) <= 75  # Slack's limit for a checkbox label
    bot = SlackInteractions(repo, FakeSlack(), SECRET)
    headers, _ = _signed({"type": "x"})
    body = urlencode({"payload": "{not json"}).encode()
    ts = headers["X-Slack-Request-Timestamp"]
    sig = "v0=" + hmac.new(SECRET.encode(), b"v0:" + ts.encode() + b":" + body,
                           hashlib.sha256).hexdigest()
    assert bot.handle({"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}, body)[0] == 400
    assert bot.handle({"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=\u00e9"},
                      body)[0] == 401
