"""Delivery channels: email, Slack, Microsoft Teams, signed webhooks, and the log.

A channel accepts some events (and optionally some workspaces). Email sends one message per
person and may carry that person's own content, such as the question a whisper asks them.
Slack and Teams post to a shared channel, so they show only events that carry no one's personal
content. Webhooks receive accepted events as signed JSON, for your own integrations: events
about people (a whisper asked or lapsed, a member's roles) and the recipients of each event only
when the webhook is configured with ``include_personal``.

Text that comes from records or people is escaped for each channel, so it cannot add links,
mentions, or formatting, and a delivery error names the host it failed to reach, never the full
URL (webhook URLs carry secrets).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import smtplib
import time
from collections.abc import Iterable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse

from .events import GROUP_SAFE, Notification, summary

log = logging.getLogger("metis.notify")


class DeliveryError(RuntimeError):
    """A delivery failed; the message names the host, never the URL."""


def post_json(url: str, *, timeout: float, **kwargs: Any) -> None:
    """POST to ``url``; failures raise ``DeliveryError`` naming only the status and host."""
    import httpx

    host = urlparse(url).hostname or "the receiver"
    try:
        httpx.post(url, timeout=timeout, **kwargs).raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DeliveryError(f"HTTP {exc.response.status_code} from {host}") from None
    except httpx.HTTPError as exc:
        raise DeliveryError(f"{exc.__class__.__name__} reaching {host}") from None


def slack_text(text: Any, limit: int = 2900) -> str:
    """Text for Slack's mrkdwn: ``&``, ``<``, and ``>`` escaped, then cut to ``limit``
    characters without splitting an escape."""
    value = str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if len(value) <= limit:
        return value
    cut = value[:limit - 1]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]
    return cut + "\u2026"


def email_of(uri: str) -> str | None:
    """The email address in a ``human:<email>`` participant URI, if it holds one."""
    if not uri.startswith("human:"):
        return None
    address = uri.split(":", 1)[1]
    return address if "@" in address and "." in address.split("@")[-1] else None


@dataclass
class Channel:
    name: str
    events: frozenset[str] = frozenset({"*"})
    workspaces: frozenset[str] = frozenset()
    public_url: str | None = None
    personal: bool = False  # one delivery per recipient

    def accepts(self, n: Notification) -> bool:
        if self.workspaces and n.workspace_id not in self.workspaces:
            return False
        return "*" in self.events or n.event in self.events

    def recipients_for(self, n: Notification) -> list[str | None]:
        """One entry per delivery: a recipient for personal channels, ``None`` otherwise."""
        return [None]

    def link(self) -> str | None:
        return f"{self.public_url.rstrip('/')}/app" if self.public_url else None

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        raise NotImplementedError


@dataclass
class LogChannel(Channel):
    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        log.info("notification %s %s to %s: %s", delivery_id, n.event, ", ".join(n.recipients),
                 summary(n, personal=False))


def webhook_signature(secret: str, timestamp: str, body: bytes) -> str:
    """``X-Metis-Signature``: ``sha256=`` HMAC-SHA256 of ``<timestamp>.<body>``. A receiver
    recomputes it, refuses timestamps more than a few minutes old, and ignores a delivery id it
    has seen (delivery is at least once)."""
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


@dataclass
class WebhookChannel(Channel):
    url: str = ""
    secret: str | None = None
    timeout: float = 10.0
    include_personal: bool = False

    def accepts(self, n: Notification) -> bool:
        return (self.include_personal or n.event in GROUP_SAFE) and super().accepts(n)

    def body(self, n: Notification, delivery_id: int) -> bytes:
        data = n.as_dict()
        if not self.include_personal:
            data.pop("recipients", None)
        payload = {"id": delivery_id, **data, "summary": summary(n, personal=False)}
        if self.link():
            payload["link"] = self.link()
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        body = self.body(n, delivery_id)
        timestamp = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Metis-Event": n.event,
                   "X-Metis-Delivery": str(delivery_id), "X-Metis-Timestamp": timestamp}
        if self.secret:
            headers["X-Metis-Signature"] = webhook_signature(self.secret, timestamp, body)
        post_json(self.url, content=body, headers=headers, timeout=self.timeout)


@dataclass
class SlackChannel(Channel):
    """A Slack incoming webhook, which posts to one channel."""

    webhook_url: str = ""
    timeout: float = 10.0

    def accepts(self, n: Notification) -> bool:
        return n.event in GROUP_SAFE and super().accepts(n)

    def message(self, n: Notification) -> dict[str, Any]:
        text = slack_text(summary(n, personal=False))
        if self.link():
            text += f" <{self.link()}|Open Metis>"
        return {"text": text}

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        post_json(self.webhook_url, json=self.message(n), timeout=self.timeout)


@dataclass
class TeamsChannel(Channel):
    """A Microsoft Teams workflow webhook, which posts an Adaptive Card to one channel."""

    webhook_url: str = ""
    timeout: float = 10.0

    def accepts(self, n: Notification) -> bool:
        return n.event in GROUP_SAFE and super().accepts(n)

    def message(self, n: Notification) -> dict[str, Any]:
        card: dict[str, Any] = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard", "version": "1.4",
            "body": [{"type": "TextBlock", "text": "Metis", "weight": "Bolder"},
                     # a plain text run: Teams renders no markdown or links in it
                     {"type": "RichTextBlock", "inlines": [
                         {"type": "TextRun", "text": summary(n, personal=False)[:2000]}]}],
        }
        if self.link():
            card["actions"] = [{"type": "Action.OpenUrl", "title": "Open Metis", "url": self.link()}]
        return {"type": "message", "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        post_json(self.webhook_url, json=self.message(n), timeout=self.timeout)


@dataclass
class EmailChannel(Channel):
    """Email through an SMTP server, one message per person."""

    host: str = ""
    port: int = 587
    username: str | None = None
    password: str | None = None
    sender: str = "metis@localhost"
    starttls: bool = True
    timeout: float = 20.0
    personal: bool = True

    def recipients_for(self, n: Notification) -> list[str | None]:
        return [uri for uri in n.recipients if email_of(uri)]

    def accepts(self, n: Notification) -> bool:
        return super().accepts(n) and bool(self.recipients_for(n))

    def message(self, n: Notification, recipient: str) -> EmailMessage:
        text = summary(n, personal=True)
        line = " ".join("".join(c if c.isprintable() else " " for c in text).split())
        msg = EmailMessage()
        msg["Subject"] = f"[Metis] {line if len(line) <= 120 else line[:117] + '...'}"
        msg["From"] = self.sender
        msg["To"] = email_of(recipient)
        body = text + (f"\n\nOpen Metis: {self.link()}" if self.link() else "")
        msg.set_content(body + "\n\nYou receive this because of your role in this Metis workspace.")
        return msg

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        if recipient is None:
            raise ValueError("An email delivery needs a recipient.")
        msg = self.message(n, recipient)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)


def deliveries(channels: Iterable[Channel], n: Notification) -> list[tuple[Channel, str | None]]:
    """Every (channel, recipient) delivery a notification needs."""
    out = []
    for channel in channels:
        if channel.accepts(n):
            out.extend((channel, r) for r in channel.recipients_for(n))
    return out
