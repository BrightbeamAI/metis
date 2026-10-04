"""Notification settings: channels from a YAML file and ``METIS_*`` shortcuts.

A file named by ``METIS_NOTIFICATIONS_FILE`` lists channels::

    public_url: https://metis.example.com
    channels:
      - name: email
        type: email
        events: [whisper.asked, review.requested, review.approval, review.decided]
        smtp: {host: smtp.example.com, port: 587, username: metis,
               password_env: METIS_SMTP_PASSWORD, from: metis@example.com}
      - name: quality-channel
        type: slack            # or teams
        webhook_url_env: METIS_SLACK_WEBHOOK_URL
        workspaces: [wsp_plant_a]
      - name: integrations
        type: webhook
        url: https://hooks.example.com/metis
        secret_env: METIS_WEBHOOK_SECRET

Secrets are read from the environment variables the file names (``*_env``). Without a file, the
shortcuts ``METIS_NOTIFY_WEBHOOK_URL``, ``METIS_NOTIFY_SLACK_WEBHOOK_URL``,
``METIS_NOTIFY_TEAMS_WEBHOOK_URL``, and ``METIS_SMTP_HOST`` each add a channel.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .channels import (
    Channel,
    EmailChannel,
    LogChannel,
    SlackChannel,
    TeamsChannel,
    WebhookChannel,
)
from .events import EVENTS, GROUP_SAFE

# What each kind of channel carries unless its configuration says otherwise.
DEFAULT_EVENTS: dict[str, frozenset[str]] = {
    "email": frozenset(EVENTS) - {"whisper.lapsed"},
    "slack": frozenset(GROUP_SAFE),
    "teams": frozenset(GROUP_SAFE),
    "webhook": frozenset({"*"}),
    "log": frozenset({"*"}),
}


def _secret(spec: Mapping[str, Any], key: str, env: Mapping[str, str]) -> str | None:
    if spec.get(f"{key}_env"):
        value = env.get(str(spec[f"{key}_env"]))
        if not value:
            raise ValueError(f"Environment variable {spec[f'{key}_env']} is not set.")
        return value
    return spec.get(key)


def channel_from(spec: Mapping[str, Any], *, public_url: str | None,
                 env: Mapping[str, str]) -> Channel:
    kind = str(spec.get("type", "")).lower()
    if kind not in DEFAULT_EVENTS:
        raise ValueError(f"Unknown channel type {kind!r}; use email, slack, teams, webhook, or log.")
    events = frozenset(spec.get("events") or DEFAULT_EVENTS[kind])
    unknown = events - set(EVENTS) - {"*"}
    if unknown:
        raise ValueError(f"Unknown notification events: {', '.join(sorted(unknown))}")
    common: dict[str, Any] = {"name": str(spec.get("name") or kind), "events": events,
                              "workspaces": frozenset(spec.get("workspaces") or ()),
                              "public_url": public_url}
    if kind == "webhook":
        url = _secret(spec, "url", env)
        if not url:
            raise ValueError("A webhook channel needs a url.")
        return WebhookChannel(**common, url=url, secret=_secret(spec, "secret", env))
    if kind in ("slack", "teams"):
        url = _secret(spec, "webhook_url", env)
        if not url:
            raise ValueError(f"A {kind} channel needs a webhook_url.")
        return (SlackChannel if kind == "slack" else TeamsChannel)(**common, webhook_url=url)
    if kind == "email":
        smtp = dict(spec.get("smtp") or {})
        if not smtp.get("host"):
            raise ValueError("An email channel needs smtp.host.")
        return EmailChannel(**common, host=str(smtp["host"]), port=int(smtp.get("port", 587)),
                            username=smtp.get("username"), password=_secret(smtp, "password", env),
                            sender=str(smtp.get("from") or "metis@localhost"),
                            starttls=bool(smtp.get("starttls", True)))
    return LogChannel(**common)


def load_channels(env: Mapping[str, str] | None = None) -> tuple[list[Channel], str | None]:
    """The configured channels and the public URL links point to."""
    env = os.environ if env is None else env
    public_url = env.get("METIS_PUBLIC_URL") or None
    path = env.get("METIS_NOTIFICATIONS_FILE")
    if path:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        public_url = data.get("public_url") or public_url
        channels = [channel_from(spec, public_url=public_url, env=env)
                    for spec in data.get("channels") or []]
    else:
        specs: list[dict[str, Any]] = []
        if env.get("METIS_NOTIFY_WEBHOOK_URL"):
            specs.append({"type": "webhook", "url_env": "METIS_NOTIFY_WEBHOOK_URL",
                          **({"secret_env": "METIS_NOTIFY_WEBHOOK_SECRET"}
                             if env.get("METIS_NOTIFY_WEBHOOK_SECRET") else {})})
        if env.get("METIS_NOTIFY_SLACK_WEBHOOK_URL"):
            specs.append({"type": "slack", "webhook_url_env": "METIS_NOTIFY_SLACK_WEBHOOK_URL"})
        if env.get("METIS_NOTIFY_TEAMS_WEBHOOK_URL"):
            specs.append({"type": "teams", "webhook_url_env": "METIS_NOTIFY_TEAMS_WEBHOOK_URL"})
        if env.get("METIS_SMTP_HOST"):
            smtp: dict[str, Any] = {"host": env["METIS_SMTP_HOST"],
                                    "port": int(env.get("METIS_SMTP_PORT") or 587),
                                    "username": env.get("METIS_SMTP_USERNAME") or None,
                                    "from": env.get("METIS_SMTP_FROM") or "metis@localhost",
                                    "starttls": (env.get("METIS_SMTP_STARTTLS") or "true").lower()
                                    not in ("0", "false", "no")}
            if env.get("METIS_SMTP_PASSWORD"):
                smtp["password_env"] = "METIS_SMTP_PASSWORD"
            specs.append({"type": "email", "smtp": smtp})
        if (env.get("METIS_NOTIFY_LOG") or "").lower() in ("1", "true", "yes"):
            specs.append({"type": "log"})
        channels = [channel_from(spec, public_url=public_url, env=env) for spec in specs]
    names = [c.name for c in channels]
    if len(names) != len(set(names)):
        raise ValueError("Notification channel names must be unique.")
    return channels, public_url
