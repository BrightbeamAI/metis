"""Notifications for people and systems: what happened in a workspace, delivered by email,
Slack, Microsoft Teams, signed webhooks, or the log.

The SQL repository plans notifications inside each write's transaction and stores them in an
outbox; the ``Dispatcher`` delivers them, with retries.
"""
from .channels import (
    Channel,
    EmailChannel,
    LogChannel,
    SlackChannel,
    TeamsChannel,
    WebhookChannel,
)
from .config import load_channels
from .events import EVENTS, Notification
from .outbox import Dispatcher, Notifier
from .planner import Planner

__all__ = [
    "EVENTS",
    "Channel",
    "Dispatcher",
    "EmailChannel",
    "LogChannel",
    "Notification",
    "Notifier",
    "Planner",
    "SlackChannel",
    "TeamsChannel",
    "WebhookChannel",
    "load_channels",
]
