"""Delivery channels: email, Slack, Microsoft Teams, signed webhooks, and the log.

A channel accepts some events (and optionally some workspaces). Email sends one message per
person and may carry that person's own content, such as the question a whisper asks them.
Slack and Teams post to a shared channel, so they show only events that carry no one's personal
content. Webhooks receive every accepted event as signed JSON, for your own integrations.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import smtplib
from collections.abc import Iterable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from .events import GROUP_SAFE, Notification, summary

log = logging.getLogger("metis.notify")


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


@dataclass
class WebhookChannel(Channel):
    url: str = ""
    secret: str | None = None
    timeout: float = 10.0

    def body(self, n: Notification, delivery_id: int) -> bytes:
        payload = {"id": delivery_id, **n.as_dict(), "summary": summary(n, personal=False)}
        if self.link():
            payload["link"] = self.link()
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        import httpx

        body = self.body(n, delivery_id)
        headers = {"Content-Type": "application/json", "X-Metis-Event": n.event,
                   "X-Metis-Delivery": str(delivery_id)}
        if self.secret:
            digest = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-Metis-Signature"] = f"sha256={digest}"
        httpx.post(self.url, content=body, headers=headers, timeout=self.timeout).raise_for_status()


@dataclass
class SlackChannel(Channel):
    """A Slack incoming webhook, which posts to one channel."""

    webhook_url: str = ""
    timeout: float = 10.0

    def accepts(self, n: Notification) -> bool:
        return n.event in GROUP_SAFE and super().accepts(n)

    def message(self, n: Notification) -> dict[str, Any]:
        text = summary(n, personal=False)
        if self.link():
            text += f" <{self.link()}|Open Metis>"
        return {"text": text}

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        import httpx

        httpx.post(self.webhook_url, json=self.message(n), timeout=self.timeout).raise_for_status()


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
                     {"type": "TextBlock", "text": summary(n, personal=False), "wrap": True}],
        }
        if self.link():
            card["actions"] = [{"type": "Action.OpenUrl", "title": "Open Metis", "url": self.link()}]
        return {"type": "message", "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}

    def deliver(self, n: Notification, recipient: str | None, delivery_id: int) -> None:
        import httpx

        httpx.post(self.webhook_url, json=self.message(n), timeout=self.timeout).raise_for_status()


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
        msg = EmailMessage()
        msg["Subject"] = f"[Metis] {text if len(text) <= 120 else text[:117] + '...'}"
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
