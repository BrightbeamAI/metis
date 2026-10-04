"""Whispers in Microsoft Teams: an Adaptive Card from the Metis bot, answered in place.

The bot sends each whisper to the worker in a personal chat, as a card with the question, the
record that prompted it, a consent toggle, and answer buttons; "Correct it" opens a field for the
worker's own words. Teams sends the answer to the bot's messaging endpoint signed by the Bot
Framework; Metis checks the token, looks up the worker's email in Teams, records the answer as
that worker, and replaces the card with a confirmation.

A bot can start a personal chat only with someone who has the Metis app installed, so install it
for workers (an admin can do this for everyone). Each installation tells the bot where to reach
that person, and Metis remembers it.

Register an Azure Bot with the Microsoft Teams channel and the messaging endpoint
``https://<server>/integrations/teams/messages``, then set ``METIS_TEAMS_APP_ID``,
``METIS_TEAMS_APP_PASSWORD``, and, for a single-tenant bot, ``METIS_TEAMS_TENANT_ID``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..identity import AuthenticationError
from ..notify.channels import Channel, email_of
from ..notify.events import Notification
from .answers import CONSENT_TEXT, LABELS, participant_for, record_answer

log = logging.getLogger("metis.connectors")

OPENID_CONFIG = "https://login.botframework.com/v1/.well-known/openidconfiguration"
ISSUER = "https://api.botframework.com"
SCOPE = "https://api.botframework.com/.default"


class TeamsBotAuth:
    """Validates the JWT the Bot Framework connector sends with each activity."""

    def __init__(self, app_id: str, *, key_resolver: Callable[[str], Any] | None = None,
                 openid_config: str = OPENID_CONFIG, leeway: int = 300) -> None:
        self.app_id = app_id
        self.openid_config = openid_config
        self.leeway = leeway
        self._resolver = key_resolver

    def _key(self, token: str) -> Any:
        if self._resolver is None:
            import httpx
            import jwt

            jwks_uri = httpx.get(self.openid_config, timeout=10).json()["jwks_uri"]
            client = jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)
            self._resolver = lambda t: client.get_signing_key_from_jwt(t).key
        return self._resolver(token)

    def verify(self, authorization: str | None, service_url: str | None) -> dict[str, Any]:
        import jwt

        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("The activity carries no Bot Framework token.")
        try:
            claims = jwt.decode(token, self._key(token), algorithms=["RS256"], audience=self.app_id,
                                issuer=ISSUER, leeway=self.leeway)
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid Bot Framework token: {exc}") from None
        claimed = claims.get("serviceurl") or claims.get("serviceUrl")
        if claimed and service_url and claimed.rstrip("/") != service_url.rstrip("/"):
            raise AuthenticationError("The token was issued for another service URL.")
        return claims


class BotConnector:
    """Sends activities through the Bot Framework connector, with the bot's own token."""

    def __init__(self, app_id: str, app_password: str, *, tenant_id: str | None = None,
                 http: Any = None, token_url: str | None = None) -> None:
        from ..client import ClientCredentials

        self.app_id = app_id
        self._http = http
        url = token_url or (f"https://login.microsoftonline.com/{tenant_id or 'botframework.com'}"
                            "/oauth2/v2.0/token")
        self.credentials = ClientCredentials(url, app_id, app_password, scope=SCOPE, http=http)

    def _client(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=15)
        return self._http

    def _url(self, service_url: str, path: str) -> str:
        return f"{service_url.rstrip('/')}/v3/{path}"

    def _send(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client().request(method, url, json=body, headers={
            "Authorization": f"Bearer {self.credentials.token()}"})
        response.raise_for_status()
        return response.json() if response.content else {}

    def send(self, service_url: str, conversation_id: str, activity: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", self._url(service_url, f"conversations/{conversation_id}/activities"),
                          activity)

    def update(self, service_url: str, conversation_id: str, activity_id: str,
               activity: dict[str, Any]) -> dict[str, Any]:
        return self._send("PUT", self._url(
            service_url, f"conversations/{conversation_id}/activities/{activity_id}"), activity)

    def member(self, service_url: str, conversation_id: str, member_id: str) -> dict[str, Any]:
        return self._send("GET", self._url(
            service_url, f"conversations/{conversation_id}/members/{member_id}"))


def _card(body: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    card: dict[str, Any] = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                            "type": "AdaptiveCard", "version": "1.4", "body": body}
    if actions:
        card["actions"] = actions
    return {"type": "message", "attachments": [
        {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


def whisper_card(n: Notification) -> dict[str, Any]:
    """The card for a whisper: question, record, consent toggle, and answer actions."""
    s = n.subject
    data = {"metis": "answer", "w": n.workspace_id, "id": s.get("whisper_id")}
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": n.workspace_name or n.workspace_id, "isSubtle": True,
         "size": "Small"},
        {"type": "TextBlock", "text": s.get("question", ""), "wrap": True, "weight": "Bolder",
         "size": "Medium"},
    ]
    if s.get("observation"):
        body.append({"type": "TextBlock", "text": f"What the record shows: {s['observation']}",
                     "wrap": True})
    body.append({"type": "Input.Toggle", "id": "consent", "title": CONSENT_TEXT,
                 "valueOn": "granted", "valueOff": "declined", "value": "declined", "wrap": True})
    submit = [{"type": "Action.Submit", "title": LABELS[r], "data": {**data, "r": r},
               **({"style": "positive"} if r == "confirm" else {})} for r in ("confirm",)]
    correct = {"type": "Action.ShowCard", "title": LABELS["correct"], "card": {
        "type": "AdaptiveCard", "body": [{"type": "Input.Text", "id": "corrected_text",
                                          "isMultiline": True,
                                          "placeholder": "Describe it in your own words"}],
        "actions": [{"type": "Action.Submit", "title": "Send", "data": {**data, "r": "correct"}}]}}
    later = [{"type": "Action.Submit", "title": LABELS[r], "data": {**data, "r": r}}
             for r in ("defer", "dismiss")]
    return _card(body, submit + [correct] + later)


@dataclass
class TeamsWhisperChannel(Channel):
    """Delivers ``whisper.asked`` as a card in the worker's personal chat with the Metis bot."""

    connector: BotConnector | None = None
    directory: Callable[[str, str], dict[str, Any] | None] | None = None
    events: frozenset[str] = frozenset({"whisper.asked"})
    personal: bool = True

    def recipients_for(self, n: Notification) -> list[str | None]:
        return [uri for uri in n.recipients if email_of(uri)]

    def accepts(self, n: Notification) -> bool:
        return n.event == "whisper.asked" and super().accepts(n) and bool(self.recipients_for(n))

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        if self.connector is None or self.directory is None or recipient is None:
            raise ValueError("The Teams channel is not set up.")
        where = self.directory("teams", recipient)
        if where is None:
            raise LookupError(f"{recipient} has not installed the Metis app in Teams yet.")
        self.connector.send(where["service_url"], where["conversation_id"], whisper_card(n))


class TeamsBot:
    """The messaging endpoint: remembers where to reach each person, and records answers."""

    def __init__(self, repo: Any, auth: TeamsBotAuth, connector: BotConnector) -> None:
        self.repo = repo
        self.auth = auth
        self.connector = connector

    def _remember(self, activity: dict[str, Any], member: dict[str, Any]) -> str | None:
        """Store where to reach ``member`` (a personal chat) and return their participant."""
        conversation = activity.get("conversation") or {}
        service_url = activity.get("serviceUrl", "")
        try:
            profile = self.connector.member(service_url, conversation["id"], member["id"])
        except Exception as exc:  # Teams could not describe the member; try again next time
            log.warning("Teams member lookup failed: %s", exc)
            return None
        participant = participant_for(profile.get("email") or profile.get("userPrincipalName"))
        if participant is None:
            return None
        tenant = conversation.get("tenantId") or ((activity.get("channelData") or {})
                                                  .get("tenant") or {}).get("id")
        self.repo.save_chat_identity("teams", participant, member["id"], {
            "service_url": service_url, "conversation_id": conversation["id"],
            "tenant_id": tenant, "bot_id": (activity.get("recipient") or {}).get("id")})
        return participant

    def handle(self, headers: dict[str, str], activity: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        lowered = {k.lower(): v for k, v in headers.items()}
        try:
            self.auth.verify(lowered.get("authorization"), activity.get("serviceUrl"))
        except AuthenticationError as exc:
            return 401, {"error": str(exc)}
        personal = (activity.get("conversation") or {}).get("conversationType") == "personal"
        kind = activity.get("type")
        if kind == "conversationUpdate" and personal:
            bot = (activity.get("recipient") or {}).get("id")
            for member in activity.get("membersAdded") or []:
                if member.get("id") != bot:
                    self._remember(activity, member)
            return 200, None
        if kind == "installationUpdate" and personal:
            self._remember(activity, activity.get("from") or {})
            return 200, None
        if kind == "message" and personal:
            sender = activity.get("from") or {}
            participant = (self.repo.chat_participant("teams", sender.get("id", ""))
                           or self._remember(activity, sender))
            value = activity.get("value") or {}
            if value.get("metis") == "answer":
                return 200, self._answer(activity, participant, value)
            return 200, None
        return 200, None

    def _answer(self, activity: dict[str, Any], participant: str | None,
                value: dict[str, Any]) -> None:
        try:
            if participant is None:
                raise PermissionError("Teams has no email for you, so Metis cannot tell who you are.")
            text = record_answer(self.repo, participant, value.get("w"), value.get("id"),
                                 value.get("r"), value.get("consent") == "granted",
                                 corrected_text=value.get("corrected_text"))
            done = True
        except (PermissionError, LookupError, ValueError) as exc:
            text, done = str(exc), False
        conversation = (activity.get("conversation") or {}).get("id")
        service_url = activity.get("serviceUrl", "")
        reply = _card([{"type": "TextBlock", "text": text, "wrap": True}])
        try:
            if done and activity.get("replyToId"):
                self.connector.update(service_url, conversation, activity["replyToId"], reply)
            else:
                self.connector.send(service_url, conversation, reply)
        except Exception as exc:  # the answer is recorded; only the confirmation failed
            log.warning("Teams reply failed: %s", exc)
        return None
