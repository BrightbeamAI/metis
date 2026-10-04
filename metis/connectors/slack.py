"""Whispers in Slack: a direct message from the Metis app, answered with a click.

The app sends each whisper to the worker as a direct message with the question, the record that
prompted it, a consent box, and answer buttons; "Correct it" opens a form for the worker's own
words. Slack signs every interaction it sends back, and Metis checks the signature, looks up the
worker's email through Slack, and records the answer as that worker.

The Slack app needs the bot scopes ``chat:write``, ``users:read``, and ``users:read.email``, and
its Interactivity request URL set to ``https://<server>/integrations/slack/interactions``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from ..notify.channels import Channel, email_of
from ..notify.events import Notification
from .answers import CONSENT_TEXT, LABELS, participant_for, record_answer


class SlackError(RuntimeError):
    """The Slack Web API refused a call."""


class SlackAPI:
    """The few Slack Web API methods Metis uses."""

    def __init__(self, token: str, *, http: Any = None, base_url: str = "https://slack.com/api",
                 timeout: float = 10.0) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = http
        self._ids: dict[str, str] = {}
        self._emails: dict[str, str | None] = {}

    def _client(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def call(self, method: str, **payload: Any) -> dict[str, Any]:
        response = self._client().post(f"{self.base_url}/{method}", json=payload,
                                       headers={"Authorization": f"Bearer {self.token}"})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise SlackError(f"Slack {method}: {body.get('error', 'failed')}")
        return body

    def get(self, method: str, **params: Any) -> dict[str, Any]:
        response = self._client().get(f"{self.base_url}/{method}", params=params,
                                      headers={"Authorization": f"Bearer {self.token}"})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise SlackError(f"Slack {method}: {body.get('error', 'failed')}")
        return body

    def user_id_for(self, email: str) -> str:
        if email not in self._ids:
            self._ids[email] = self.get("users.lookupByEmail", email=email)["user"]["id"]
        return self._ids[email]

    def email_of(self, user_id: str) -> str | None:
        if user_id not in self._emails:
            profile = self.get("users.info", user=user_id)["user"].get("profile") or {}
            self._emails[user_id] = profile.get("email")
        return self._emails[user_id]

    def post_response(self, response_url: str, message: dict[str, Any]) -> None:
        self._client().post(response_url, json=message).raise_for_status()


def verify_signature(signing_secret: str, headers: dict[str, str], body: bytes, *,
                     now: float | None = None, tolerance: int = 300) -> bool:
    """Slack's request signature: ``v0=`` HMAC-SHA256 of ``v0:<timestamp>:<body>``."""
    lowered = {k.lower(): v for k, v in headers.items()}
    timestamp = lowered.get("x-slack-request-timestamp", "")
    signature = lowered.get("x-slack-signature", "")
    if not timestamp.isdigit() or abs((now or time.time()) - int(timestamp)) > tolerance:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def whisper_blocks(n: Notification) -> list[dict[str, Any]]:
    """The direct message for a whisper: question, record, consent box, and answer buttons."""
    s = n.subject
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn",
                                     "text": f"*{n.workspace_name or n.workspace_id}*\n{s.get('question', '')}"}},
    ]
    if s.get("observation"):
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"What the record shows: {s['observation']}"}]})
    blocks.append({"type": "actions", "block_id": "consent", "elements": [{
        "type": "checkboxes", "action_id": "consent",
        "options": [{"text": {"type": "plain_text", "text": CONSENT_TEXT}, "value": "granted"}]}]})
    blocks.append({"type": "actions", "block_id": "answer", "elements": [
        {"type": "button", "action_id": f"answer_{response}",
         "text": {"type": "plain_text", "text": LABELS[response]},
         "value": json.dumps({"w": n.workspace_id, "id": s.get("whisper_id"), "r": response}),
         **({"style": "primary"} if response == "confirm" else {})}
        for response in ("confirm", "correct", "defer", "dismiss")]})
    return blocks


@dataclass
class SlackWhisperChannel(Channel):
    """Delivers ``whisper.asked`` as a direct message to the worker."""

    api: SlackAPI | None = None
    events: frozenset[str] = frozenset({"whisper.asked"})
    personal: bool = True

    def recipients_for(self, n: Notification) -> list[str | None]:
        return [uri for uri in n.recipients if email_of(uri)]

    def accepts(self, n: Notification) -> bool:
        return n.event == "whisper.asked" and super().accepts(n) and bool(self.recipients_for(n))

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        if self.api is None or recipient is None:
            raise ValueError("The Slack channel has no API client or recipient.")
        user = self.api.user_id_for(email_of(recipient))
        self.api.call("chat.postMessage", channel=user, blocks=whisper_blocks(n),
                      text=f"A question about your work in {n.workspace_name}: "
                           f"{n.subject.get('question', '')}")


def _correction_view(workspace: str, whisper_id: str) -> dict[str, Any]:
    return {
        "type": "modal", "callback_id": "metis_correct",
        "private_metadata": json.dumps({"w": workspace, "id": whisper_id}),
        "title": {"type": "plain_text", "text": "Correct the account"},
        "submit": {"type": "plain_text", "text": "Send"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "input", "block_id": "text", "label": {"type": "plain_text", "text": "In your own words"},
             "element": {"type": "plain_text_input", "action_id": "text", "multiline": True}},
            {"type": "input", "block_id": "consent", "label": {"type": "plain_text", "text": "Consent"},
             "element": {"type": "checkboxes", "action_id": "consent", "options": [
                 {"text": {"type": "plain_text", "text": CONSENT_TEXT}, "value": "granted"}]}},
        ],
    }


def _checked(state: dict[str, Any], block: str, action: str) -> bool:
    element = ((state.get("values") or {}).get(block) or {}).get(action) or {}
    return any(o.get("value") == "granted" for o in element.get("selected_options") or [])


class SlackInteractions:
    """Answers whispers from Slack's signed interaction requests."""

    def __init__(self, repo: Any, api: SlackAPI, signing_secret: str) -> None:
        self.repo = repo
        self.api = api
        self.signing_secret = signing_secret

    def _participant(self, payload: dict[str, Any]) -> str:
        who = participant_for(self.api.email_of(payload["user"]["id"]))
        if who is None:
            raise PermissionError("Slack has no email for you, so Metis cannot tell who you are.")
        return who

    def handle(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any] | None]:
        """Process one interaction; return the HTTP status and any JSON body for Slack."""
        if not verify_signature(self.signing_secret, headers, body):
            return 401, {"error": "invalid signature"}
        payload = json.loads(parse_qs(body.decode("utf-8")).get("payload", ["{}"])[0])
        kind = payload.get("type")
        if kind == "block_actions":
            return 200, self._button(payload)
        if kind == "view_submission" and (payload.get("view") or {}).get("callback_id") == "metis_correct":
            return 200, self._correction(payload)
        return 200, None

    def _button(self, payload: dict[str, Any]) -> None:
        action = next((a for a in payload.get("actions") or []
                       if str(a.get("action_id", "")).startswith("answer_")), None)
        if action is None:
            return None  # the consent box changed; nothing to record yet
        value = json.loads(action.get("value") or "{}")
        response, workspace, whisper_id = value.get("r"), value.get("w"), value.get("id")
        if response == "correct":
            self.api.call("views.open", trigger_id=payload["trigger_id"],
                          view=_correction_view(workspace, whisper_id))
            return None
        consent = _checked(payload.get("state") or {}, "consent", "consent")
        try:
            text = record_answer(self.repo, self._participant(payload), workspace, whisper_id,
                                 response, consent)
            message = {"replace_original": True, "text": text}
        except (PermissionError, LookupError, ValueError) as exc:
            message = {"replace_original": False, "response_type": "ephemeral", "text": str(exc)}
        if payload.get("response_url"):
            self.api.post_response(payload["response_url"], message)
        return None

    def _correction(self, payload: dict[str, Any]) -> dict[str, Any]:
        view = payload["view"]
        meta = json.loads(view.get("private_metadata") or "{}")
        state = view.get("state") or {}
        text = (((state.get("values") or {}).get("text") or {}).get("text") or {}).get("value")
        consent = _checked(state, "consent", "consent")
        try:
            record_answer(self.repo, self._participant(payload), meta.get("w"), meta.get("id"),
                          "correct", consent, corrected_text=text)
        except (PermissionError, LookupError, ValueError) as exc:
            return {"response_action": "errors", "errors": {"text": str(exc)}}
        return {"response_action": "clear"}
