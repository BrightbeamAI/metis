"""Notifications: planned inside each write, queued in the outbox, delivered with retries."""
import datetime as dt
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field

import pytest

from metis.conditions.context import TacitContext
from metis.consent.contestability import ContestAction
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.governance.membership import Member, Role
from metis.notify import (
    Channel,
    Dispatcher,
    EmailChannel,
    Notification,
    Notifier,
    SlackChannel,
    TeamsChannel,
    WebhookChannel,
    load_channels,
)
from metis.storage.repository import WorkspaceSettings
from metis.storage.sql import SqlRepository

ADMIN = "human:admin@example.com"
WORKER, R1, R2 = "human:wendy@example.com", "human:rhea@example.com", "human:raj@example.com"
AGENT, CMMS = "agent:shift-assistant", "agent:cmms-connector"
PUMP = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load")
RISKY = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load",
                     risk_class="high")
WS = "wsp_plant_a"


@dataclass
class Recorder(Channel):
    sent: list = field(default_factory=list)
    fail_times: int = 0

    def deliver(self, n, recipient, delivery_id):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("the receiver is down")
        self.sent.append((n.event, recipient, n))


@dataclass
class PerPerson(Recorder):
    personal: bool = True

    def recipients_for(self, n):
        return list(n.recipients)


@pytest.fixture()
def setup(tmp_path):
    group, people = Recorder(name="group"), PerPerson(name="people")
    repo = SqlRepository(f"sqlite:///{tmp_path / 'n.db'}",
                         notifier=Notifier([group, people], public_url="https://metis.example.com"))
    members = [Member(uri=WORKER, roles=[Role.worker]), Member(uri=R1, roles=[Role.reviewer]),
               Member(uri=R2, roles=[Role.reviewer, Role.escalation]),
               Member(uri=AGENT, roles=[Role.agent]), Member(uri=CMMS, roles=[Role.capture])]
    repo.create(WorkspaceSettings(id=WS, name="Plant A", members=members,
                                  whisper_deadline_ms=3600_000), by=ADMIN)
    dispatcher = Dispatcher(repo, [group, people])
    yield repo, dispatcher, group, people
    repo.close()


def _deliver(dispatcher, people):
    people.sent.clear()
    dispatcher.run_once()
    return [(event, who) for event, who, _ in people.sent]


def _ask(engine, obs_id="OBS-1"):
    return engine.begin_capture(
        {"observation_id": obs_id, "work_as_done": "Ease back earlier.", "context": PUMP},
        consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=WORKER,
        submitted_by=CMMS, category="K7_sensory", conditions=PUMP)


def test_the_loop_notifies_each_person_once_at_each_step(setup):
    repo, dispatcher, group, people = setup
    sent = _deliver(dispatcher, people)
    assert sorted(sent) == sorted([("member.changed", u) for u in (WORKER, R1, R2, AGENT, CMMS)])

    pending = repo.write(WS, _ask)
    sent = _deliver(dispatcher, people)
    assert sent == [("whisper.asked", WORKER)]
    assert people.sent[0][2].subject["question"]

    fid = repo.write(WS, lambda e: e.answer_whisper(
        pending.whisper_id, response="confirm", answered_by=WORKER,
        consent_granted=True).fragment.fragment_id)
    assert _deliver(dispatcher, people) == []

    repo.write(WS, lambda e: e.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1))
    assert _deliver(dispatcher, people) == [("review.requested", R2)]
    repo.write(WS, lambda e: e.cast_review_vote(fid, "promoted_to_advisory", reviewer=R2))
    assert sorted(_deliver(dispatcher, people)) == sorted(
        [("review.decided", WORKER), ("review.decided", R1), ("review.decided", R2)])

    task = repo.write(WS, lambda e: e.retrieve(RISKY, requester=AGENT).escalation_task_id)
    assert _deliver(dispatcher, people) == [("escalation.opened", R2)]
    repo.write(WS, lambda e: e.decide_escalation(task, "does_not_apply", by=R2, rationale="no"))
    assert _deliver(dispatcher, people) == [("escalation.decided", AGENT)]

    repo.write(WS, lambda e: e.governance.contest(fid, ContestAction.challenge, raised_by=R1,
                                                  rationale="the cue changed"))
    assert sorted(_deliver(dispatcher, people)) == sorted(  # the contest opens a re-review
        [("fragment.contested", R2), ("fragment.contested", WORKER),
         ("review.requested", R1), ("review.requested", R2)])
    repo.write(WS, lambda e: e.governance.withdraw_consent(fid, by=WORKER, note="mine"))
    assert sorted(_deliver(dispatcher, people)) == sorted(
        [("fragment.revoked", R1), ("fragment.revoked", R2)])
    assert all(row["status"] == "delivered" for row in repo.outbox(limit=1000))


def test_a_failed_write_queues_nothing(setup):
    repo, dispatcher, group, people = setup
    dispatcher.run_once()

    def ask_then_fail(engine):
        _ask(engine)
        raise RuntimeError("dropped")

    with pytest.raises(RuntimeError):
        repo.write(WS, ask_then_fail)
    assert repo.outbox(status="pending") == []


def test_lapsed_whispers_notify_the_capture_source(setup):
    repo, dispatcher, group, people = setup
    dispatcher.run_once()
    repo.write(WS, _ask)
    dispatcher.run_once()
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    assert repo.write(WS, lambda e: e.lapse_whispers(later))
    assert _deliver(dispatcher, people) == [("whisper.lapsed", CMMS)]


def test_review_date_notices_are_sent_once(setup):
    repo, dispatcher, group, people = setup
    pending = repo.write(WS, _ask)
    fid = repo.write(WS, lambda e: e.answer_whisper(
        pending.whisper_id, response="confirm", answered_by=WORKER,
        consent_granted=True).fragment.fragment_id)
    repo.write(WS, lambda e: e.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1))
    repo.write(WS, lambda e: e.cast_review_vote(fid, "promoted_to_advisory", reviewer=R2))
    dispatcher.run_once()
    far = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=400)
    notes = repo.read(WS, lambda e: repo.notifier.review_due(e, far))
    assert [n.event for n in notes] == ["fragment.review_due"]
    assert repo.enqueue(notes) == 3  # the group channel, and one row per reviewer
    assert repo.enqueue(notes) == 0
    assert sorted(_deliver(dispatcher, people)) == sorted(
        [("fragment.review_due", R1), ("fragment.review_due", R2)])


def test_failed_deliveries_are_retried_then_marked_failed(setup):
    repo, dispatcher, group, people = setup
    dispatcher.run_once()
    flaky = Recorder(name="group", fail_times=100)
    retrying = Dispatcher(repo, [flaky], max_attempts=3)
    repo.write(WS, lambda e: e.set_member("human:rosa@example.com", ["reviewer"], by=ADMIN))
    now = dt.datetime.now(dt.timezone.utc)
    # Two deliveries: the group channel's, and Rosa's on the per-person channel, which this
    # dispatcher does not have configured.
    assert retrying.run_once(now) == {"delivered": 0, "retrying": 2, "failed": 0, "superseded": 0}
    assert retrying.run_once(now) == {"delivered": 0, "retrying": 0, "failed": 0, "superseded": 0}  # backing off
    assert retrying.run_once(now + dt.timedelta(minutes=1))["retrying"] == 2
    assert retrying.run_once(now + dt.timedelta(hours=2))["failed"] == 2
    failed = {row["channel"]: row for row in repo.outbox(status="failed")}
    assert failed["group"]["attempts"] == 3
    assert "receiver is down" in failed["group"]["last_error"]
    assert "no longer configured" in failed["people"]["last_error"]


def _note(event="review.requested", **subject):
    return Notification(event=event, workspace_id=WS, workspace_name="Plant A",
                        recipients=[R1, AGENT], subject={"fragment_id": "TF-00001", **subject})


def test_webhooks_are_signed(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    monkeypatch.setattr("httpx.post", lambda url, **kw: calls.append((url, kw)) or Response())
    channel = WebhookChannel(name="hooks", url="https://hooks.example.com/m", secret="s3cret",
                             public_url="https://metis.example.com")
    channel.deliver(_note(), None, 7)
    url, kw = calls[0]
    body, timestamp = kw["content"], kw["headers"]["X-Metis-Timestamp"]
    signed = timestamp.encode() + b"." + body  # a timestamp in the signature stops replays
    expected = "sha256=" + hmac.new(b"s3cret", signed, hashlib.sha256).hexdigest()
    assert kw["headers"]["X-Metis-Signature"] == expected
    assert abs(int(timestamp) - time.time()) < 60
    payload = json.loads(body)
    assert payload["id"] == 7 and payload["event"] == "review.requested"
    assert payload["link"] == "https://metis.example.com/app"
    assert "recipients" not in payload  # who was told is personal; off by default


def test_webhooks_carry_personal_events_only_when_configured(tmp_path):
    whisper = _note("whisper.asked", question="What cue made you pause?")
    assert not WebhookChannel(name="h", url="https://h.example.com").accepts(whisper)
    personal = WebhookChannel(name="h", url="https://h.example.com", include_personal=True)
    assert personal.accepts(whisper)
    assert json.loads(personal.body(whisper, 1))["recipients"] == [R1, AGENT]
    config = tmp_path / "n.yaml"
    config.write_text("channels:\n  - {name: h, type: webhook, url: https://h.example.com,"
                      " events: [whisper.asked]}\n")
    with pytest.raises(ValueError, match="include_personal"):
        load_channels({"METIS_NOTIFICATIONS_FILE": str(config)})


def test_delivery_errors_never_carry_the_url(monkeypatch):
    import httpx

    from metis.notify import redact

    def refuse(url, **kw):
        request = httpx.Request("POST", url)
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError(f"Client error for url '{url}'", request=request,
                                    response=response)
    monkeypatch.setattr("httpx.post", refuse)
    slack = SlackChannel(name="s", webhook_url="https://hooks.slack.com/services/T1/B2/SECRET")
    with pytest.raises(Exception) as caught:
        slack.deliver(_note(), None, 1)
    assert "SECRET" not in str(caught.value) and "hooks.slack.com" in str(caught.value)
    assert redact("failed for url 'https://u:pw@h.example.com/a/b?sig=xyz'") == \
        "failed for url 'https://h.example.com/[redacted]'"


def test_text_from_records_cannot_format_group_messages():
    hostile = _note(title="<!channel> <https://evil.example|Open Metis> [log in](https://evil)")
    slack = SlackChannel(name="s", webhook_url="https://hooks.slack.com/x").message(hostile)
    assert "<!channel>" not in slack["text"] and "&lt;!channel&gt;" in slack["text"]
    card = TeamsChannel(name="t", webhook_url="https://t.example.com/x").message(hostile)
    run = card["attachments"][0]["content"]["body"][1]
    assert run["type"] == "RichTextBlock" and run["inlines"][0]["type"] == "TextRun"
    email = EmailChannel(name="e", host="smtp.example.com").message(
        _note("review.requested", title="line one\r\nBcc: everyone@example.com"), R1)
    assert "\n" not in email["Subject"] and "\r" not in email["Subject"]


def test_group_channels_show_no_personal_content():
    slack = SlackChannel(name="s", webhook_url="https://hooks.slack.com/x")
    teams = TeamsChannel(name="t", webhook_url="https://example.webhook.office.com/x")
    whisper = _note("whisper.asked", question="What cue made you pause?")
    assert not slack.accepts(whisper) and not teams.accepts(whisper)
    assert slack.accepts(_note()) and teams.accepts(_note())
    assert "TF-00001" in slack.message(_note())["text"]
    card = teams.message(_note())["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"


def test_email_goes_to_each_person(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent.append("tls")

        def login(self, user, password):
            sent.append(("login", user))

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    channel = EmailChannel(name="email", host="smtp.example.com", username="metis",
                           password="pw", sender="metis@example.com")
    note = _note("whisper.asked", question="What cue made you pause?")
    assert channel.recipients_for(note) == [R1]  # agents have no inbox
    channel.deliver(note, R1, 3)
    msg = sent[-1]
    assert msg["To"] == "rhea@example.com" and "What cue made you pause?" in msg.get_content()
    assert sent[0] == "tls" and sent[1] == ("login", "metis")


def test_channels_from_the_environment_and_a_file(tmp_path):
    channels, url = load_channels({"METIS_NOTIFY_WEBHOOK_URL": "https://hooks.example.com",
                                   "METIS_NOTIFY_SLACK_WEBHOOK_URL": "https://hooks.slack.com/x",
                                   "METIS_SMTP_HOST": "smtp.example.com",
                                   "METIS_PUBLIC_URL": "https://metis.example.com"})
    assert [c.__class__.__name__ for c in channels] == ["WebhookChannel", "SlackChannel",
                                                        "EmailChannel"]
    assert url == "https://metis.example.com"
    config = tmp_path / "notifications.yaml"
    config.write_text(
        "public_url: https://m.example.com\n"
        "channels:\n"
        "  - name: integrations\n    type: webhook\n    url: https://h.example.com\n"
        "    secret_env: HOOK_SECRET\n    events: [review.decided]\n"
        "  - name: plant-a\n    type: teams\n    webhook_url_env: TEAMS_URL\n"
        "    workspaces: [wsp_plant_a]\n")
    channels, url = load_channels({"METIS_NOTIFICATIONS_FILE": str(config),
                                   "HOOK_SECRET": "x", "TEAMS_URL": "https://t.example.com"})
    assert [c.name for c in channels] == ["integrations", "plant-a"] and url == "https://m.example.com"
    assert channels[0].secret == "x" and channels[0].events == frozenset({"review.decided"})
    with pytest.raises(ValueError):
        load_channels({"METIS_NOTIFICATIONS_FILE": str(config)})  # the secrets are missing
    assert load_channels({}) == ([], None)


def test_a_lapsed_lease_is_taken_over_and_each_row_is_delivered_once(setup):
    repo, dispatcher, group, people = setup
    slow, fast = Dispatcher(repo, [group, people]), Dispatcher(repo, [group, people])
    now = dt.datetime.now(dt.timezone.utc)
    claimed = slow._claim(now)  # the slow dispatcher claims, then stalls past its lease
    assert claimed
    later = now + dt.timedelta(seconds=121)
    taken = fast.run_once(later)
    assert taken["delivered"] == len(claimed)
    row, token = claimed[0]
    assert slow._finish(row, token, None, later) == "superseded"  # its late result is ignored
    assert all(r["status"] == "delivered" for r in repo.outbox(limit=1000))


def test_a_row_that_keeps_crashing_its_dispatcher_ends_failed(setup):
    repo, dispatcher, group, people = setup
    crashing = Dispatcher(repo, [group, people], max_attempts=2)
    now = dt.datetime.now(dt.timezone.utc)
    for i in range(2):  # claimed, then the process dies before recording an outcome
        crashing._claim(now + dt.timedelta(minutes=5 * i))
    result = crashing.run_once(now + dt.timedelta(minutes=15))
    assert result["failed"] > 0 and result["delivered"] == 0
    assert all("Gave up after 2 attempts" in r["last_error"] for r in repo.outbox(status="failed"))


def test_failed_rows_can_be_sent_again_and_old_rows_are_cleared(setup):
    from metis.notify import prune, retry_failed

    repo, dispatcher, group, people = setup
    Dispatcher(repo, [], max_attempts=1).run_once()  # no channel configured: every row fails
    failed = repo.outbox(status="failed")
    assert failed and retry_failed(repo) == len(failed)
    assert dispatcher.run_once()["delivered"] == len(failed)
    pending = repo.write(WS, _ask)
    repo.write(WS, lambda e: e.answer_whisper(pending.whisper_id, response="confirm",
                                              answered_by=WORKER, consent_granted=True))
    dispatcher.run_once()
    far = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=31)
    assert prune(repo, retention_days=30, now=far) > 0
    assert all(r["payload"] == "{}" for r in repo.outbox(limit=1000))  # kept rows hold no content


def test_settings_are_parsed_strictly(tmp_path):
    config = tmp_path / "n.yaml"
    config.write_text('channels:\n  - {name: h, type: webhook, url: "https://h.example.com",'
                      ' include_personal: "false"}\n')
    [channel], _ = load_channels({"METIS_NOTIFICATIONS_FILE": str(config)})
    assert channel.include_personal is False
    config.write_text('channels:\n  - {name: h, type: webhook, url: "https://h.example.com",'
                      ' include_personal: "maybe"}\n')
    with pytest.raises(ValueError, match="true or false"):
        load_channels({"METIS_NOTIFICATIONS_FILE": str(config)})
    from metis.notify import redact
    assert redact("see https://h.example?token=abc") == "see https://h.example/[redacted]"
