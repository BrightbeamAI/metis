"""Whispers in Microsoft Teams: an Adaptive Card from the Metis bot, answered in place.

The bot sends each whisper to the worker in a personal chat, as a card with the question, the
record that prompted it, a consent toggle, and answer buttons; "Correct it" opens a field for the
worker's own words. Teams sends the answer to the bot's messaging endpoint signed by the Bot
Framework; Metis checks the token, the tenant, and the service it came through, looks up the
worker's email in Teams, records the answer as that worker, and replaces the card with a
confirmation.

A bot can start a personal chat only with someone who has the Metis app installed, so install it
for workers (an admin can do this for everyone). Each installation tells the bot where to reach
that person, and Metis remembers it, bound to the person's Microsoft Entra account: another
account that reports the same email is refused, never silently swapped in.

Register an Azure Bot with the Microsoft Teams channel and the messaging endpoint
``https://<server>/integrations/teams/messages``, then set ``METIS_TEAMS_APP_ID``,
``METIS_TEAMS_APP_PASSWORD``, and the tenants whose people may use it: ``METIS_TEAMS_TENANT_ID``
(single-tenant) or ``METIS_TEAMS_ALLOWED_TENANTS``.
"""
from __future__ import annotations

import fnmatch
import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..identity import AuthenticationError
from ..notify.channels import Channel, email_of
from ..notify.events import Notification
from .answers import CONSENT_TEXT, LABELS, participant_for, record_answer

log = logging.getLogger("metis.connectors")

OPENID_CONFIG = "https://login.botframework.com/v1/.well-known/openidconfiguration"
ISSUER = "https://api.botframework.com"
SCOPE = "https://api.botframework.com/.default"
CHANNEL = "msteams"
# Where the Bot Framework's Teams services live (public, GCC, GCC High, and DoD clouds).
SERVICE_HOSTS = ("smba.trafficmanager.net", "*.teams.microsoft.com", "*.teams.microsoft.us",
                 "*.botframework.com")
TEXT_LIMIT = 2000


def service_url_allowed(url: str | None, hosts: Iterable[str] = SERVICE_HOSTS) -> bool:
    """True for an https URL on one of the Bot Framework's Teams hosts."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(fnmatch.fnmatch(host, h.lower()) for h in hosts)


def _text(value: Any) -> list[dict[str, Any]]:
    """Untrusted text for a card, as a plain text run: Teams renders no markdown or links in it."""
    text = str(value or "")
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT - 1] + "…"
    return [{"type": "TextRun", "text": text}]


class TeamsBotAuth:
    """Validates the JWT the Bot Framework connector sends with each activity: its signature
    (by a key endorsed for the activity's channel), issuer, audience, expiry, and the service
    URL it was issued for."""

    def __init__(self, app_id: str, *, key_resolver: Callable[[str], Any] | None = None,
                 openid_config: str = OPENID_CONFIG, leeway: int = 300,
                 key_cache_seconds: int = 6 * 3600) -> None:
        self.app_id = app_id
        self.openid_config = openid_config
        self.leeway = leeway
        self.key_cache_seconds = key_cache_seconds
        self._resolver = key_resolver
        self._keys: dict[str, tuple[Any, list[str]]] = {}
        self._fetched = 0.0
        self._lock = threading.Lock()

    def _fetch_keys(self) -> None:
        import httpx
        import jwt

        jwks_uri = httpx.get(self.openid_config, timeout=10).json()["jwks_uri"]
        keys = {}
        for jwk in httpx.get(jwks_uri, timeout=10).json().get("keys", []):
            if jwk.get("kid"):
                keys[jwk["kid"]] = (jwt.PyJWK(jwk).key, list(jwk.get("endorsements") or []))
        self._keys, self._fetched = keys, time.monotonic()

    def _key(self, token: str) -> tuple[Any, list[str] | None]:
        """The signing key and its endorsements (``None`` when unknown)."""
        if self._resolver is not None:
            found = self._resolver(token)
            return found if isinstance(found, tuple) else (found, None)
        import jwt

        kid = jwt.get_unverified_header(token).get("kid")
        with self._lock:
            stale = time.monotonic() - self._fetched > self.key_cache_seconds
            recent = time.monotonic() - self._fetched < 60
            if stale or (kid not in self._keys and not recent):
                self._fetch_keys()
            if kid not in self._keys:
                raise AuthenticationError("The activity was signed with an unknown key.")
            return self._keys[kid]

    def verify(self, authorization: str | None, service_url: str | None,
               channel_id: str | None = None) -> dict[str, Any]:
        import jwt

        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("The activity carries no Bot Framework token.")
        try:
            key, endorsements = self._key(token)
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.app_id,
                                issuer=ISSUER, leeway=self.leeway,
                                options={"require": ["exp", "iss", "aud"]})
        except AuthenticationError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid Bot Framework token: {exc}") from None
        except Exception as exc:  # the keys could not be fetched
            raise AuthenticationError(f"The Bot Framework token cannot be checked now: {exc}") \
                from None
        claimed = claims.get("serviceurl") or claims.get("serviceUrl")
        if not claimed or not service_url or claimed.rstrip("/") != service_url.rstrip("/"):
            raise AuthenticationError("The token was not issued for this activity's service URL.")
        if channel_id and endorsements is not None and channel_id not in endorsements:
            raise AuthenticationError(f"The signing key is not endorsed for {channel_id}.")
        return claims


class BotConnector:
    """Sends activities through the Bot Framework connector, with the bot's own token, and only
    to the Bot Framework's Teams service hosts."""

    def __init__(self, app_id: str, app_password: str, *, tenant_id: str | None = None,
                 http: Any = None, token_url: str | None = None,
                 service_hosts: Iterable[str] = SERVICE_HOSTS) -> None:
        from ..client import ClientCredentials

        self.app_id = app_id
        self._http = http
        self.service_hosts = tuple(service_hosts)
        url = token_url or (f"https://login.microsoftonline.com/{tenant_id or 'botframework.com'}"
                            "/oauth2/v2.0/token")
        self.credentials = ClientCredentials(url, app_id, app_password, scope=SCOPE, http=http)

    def _client(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=15)
        return self._http

    def _url(self, service_url: str, path: str) -> str:
        if not service_url_allowed(service_url, self.service_hosts):
            raise ValueError(f"{urlparse(service_url).hostname or service_url!r} is not a Bot "
                             "Framework service host; nothing was sent.")
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


def _notice(text: str) -> dict[str, Any]:
    return _card([{"type": "RichTextBlock", "inlines": _text(text)}])


def whisper_card(n: Notification) -> dict[str, Any]:
    """The card for a whisper: question, record, consent toggle, and answer actions. Text from
    records and questions is shown as plain text runs, so it cannot add links or formatting."""
    s = n.subject
    data = {"metis": "answer", "w": n.workspace_id, "id": s.get("whisper_id")}
    body: list[dict[str, Any]] = [
        {"type": "RichTextBlock", "inlines": [{**_text(n.workspace_name or n.workspace_id)[0],
                                               "isSubtle": True, "size": "Small"}]},
        {"type": "RichTextBlock", "inlines": [{**_text(s.get("question", ""))[0],
                                               "weight": "Bolder", "size": "Medium"}]},
    ]
    if s.get("observation"):
        body.append({"type": "RichTextBlock",
                     "inlines": _text(f"What the record shows: {s['observation']}")})
    body.append({"type": "Input.Toggle", "id": "consent", "title": CONSENT_TEXT,
                 "valueOn": "granted", "valueOff": "declined", "value": "declined", "wrap": True})
    submit = [{"type": "Action.Submit", "title": LABELS[r], "data": {**data, "r": r},
               **({"style": "positive"} if r == "confirm" else {})} for r in ("confirm",)]
    correct = {"type": "Action.ShowCard", "title": LABELS["correct"], "card": {
        "type": "AdaptiveCard", "body": [{"type": "Input.Text", "id": "corrected_text",
                                          "isMultiline": True, "maxLength": 4000,
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
    """The messaging endpoint: remembers where to reach each person, and records answers.

    Activities are accepted only from the configured Microsoft Entra ``tenants``, from the
    Teams channel, and through a Bot Framework service host."""

    def __init__(self, repo: Any, auth: TeamsBotAuth, connector: BotConnector, *,
                 tenants: Iterable[str], service_hosts: Iterable[str] = SERVICE_HOSTS) -> None:
        self.repo = repo
        self.auth = auth
        self.connector = connector
        self.tenants = {t.strip().lower() for t in tenants if t and t.strip()}
        if not self.tenants:
            raise ValueError("Name the Microsoft Entra tenants whose people may use the bot.")
        self.service_hosts = tuple(service_hosts)

    @staticmethod
    def _tenant(activity: dict[str, Any]) -> str:
        conversation = activity.get("conversation") or {}
        tenant = conversation.get("tenantId") or ((activity.get("channelData") or {})
                                                  .get("tenant") or {}).get("id")
        return str(tenant or "").lower()

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
        tenant = self._tenant(activity)
        account = profile.get("aadObjectId") or member.get("aadObjectId")
        known = self.repo.chat_identity("teams", participant)
        if known is not None and (known.get("tenant_id") != tenant
                                  or (known.get("aad_object_id") or account) != account):
            log.warning("Teams account %s in tenant %s reports %s, which another Teams account "
                        "holds; not rebinding it", member.get("id"), tenant, participant)
            return None
        self.repo.save_chat_identity("teams", participant, member["id"], {
            "service_url": service_url, "conversation_id": conversation["id"],
            "tenant_id": tenant, "aad_object_id": account,
            "bot_id": (activity.get("recipient") or {}).get("id")})
        return participant

    def handle(self, headers: dict[str, str], activity: Any) -> tuple[int, dict[str, Any] | None]:
        if not isinstance(activity, dict):
            return 400, {"error": "An activity is a JSON object."}
        lowered = {k.lower(): v for k, v in headers.items()}
        try:
            self.auth.verify(lowered.get("authorization"), activity.get("serviceUrl"),
                             channel_id=activity.get("channelId"))
        except AuthenticationError as exc:
            return 401, {"error": str(exc)}
        if activity.get("channelId") != CHANNEL:
            return 403, {"error": "Only Microsoft Teams activities are accepted."}
        if self._tenant(activity) not in self.tenants:
            return 403, {"error": "This tenant may not use the Metis bot."}
        if not service_url_allowed(activity.get("serviceUrl"), self.service_hosts):
            return 403, {"error": "The activity came through an unknown service."}
        personal = (activity.get("conversation") or {}).get("conversationType") == "personal"
        kind = activity.get("type")
        if kind == "conversationUpdate" and personal:
            bot = (activity.get("recipient") or {}).get("id")
            for member in activity.get("membersAdded") or []:
                if isinstance(member, dict) and member.get("id") != bot:
                    self._remember(activity, member)
            return 200, None
        if kind == "installationUpdate" and personal:
            sender = activity.get("from") or {}
            if str(activity.get("action", "")).startswith("remove"):
                self.repo.forget_chat_identity("teams", str(sender.get("id", "")))
            else:
                self._remember(activity, sender)
            return 200, None
        if kind == "message" and personal:
            sender = activity.get("from") or {}
            participant = (self.repo.chat_participant("teams", str(sender.get("id", "")))
                           or self._remember(activity, sender))
            value = activity.get("value") or {}
            if isinstance(value, dict) and value.get("metis") == "answer":
                return 200, self._answer(activity, participant, value)
            return 200, None
        return 200, None

    def _answer(self, activity: dict[str, Any], participant: str | None,
                value: dict[str, Any]) -> None:
        try:
            if participant is None:
                raise PermissionError("Teams has no email for you, so Metis cannot tell who you are.")
            fields = [value.get(k) for k in ("w", "id", "r")]
            corrected = value.get("corrected_text")
            if not all(isinstance(f, str) for f in fields) or not isinstance(corrected, (str, type(None))):
                raise ValueError("This answer is not one Metis sent.")
            text = record_answer(self.repo, participant, *fields, value.get("consent") == "granted",
                                 corrected_text=corrected)
            done = True
        except (PermissionError, LookupError, ValueError) as exc:
            text, done = str(exc), False
        conversation = (activity.get("conversation") or {}).get("id")
        service_url = activity.get("serviceUrl", "")
        reply = _notice(text)
        try:
            if done and activity.get("replyToId"):
                self.connector.update(service_url, conversation, activity["replyToId"], reply)
            else:
                self.connector.send(service_url, conversation, reply)
        except Exception as exc:  # the answer is recorded; only the confirmation failed
            log.warning("Teams reply failed: %s", exc)
        return None
