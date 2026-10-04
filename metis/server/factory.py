"""The server's repository and notification channels, built from its settings.

The server and the ``metis server`` commands both build them here, so a notification queued or
delivered from the command line goes through the same channels as one from the server.
"""
from __future__ import annotations

from typing import Any

from .settings import ServerSettings


def chat_integrations(settings: ServerSettings) -> tuple[Any, Any, list[Any]]:
    """The Slack and Teams clients the settings configure, and their whisper channels."""
    settings.check_integrations()
    slack_api = teams_connector = None
    channels: list[Any] = []
    if settings.slack_bot_token:
        from ..connectors.slack import SlackAPI, SlackWhisperChannel

        slack_api = SlackAPI(settings.slack_bot_token)
        channels.append(SlackWhisperChannel(name="slack-whispers", api=slack_api,
                                            public_url=settings.public_url))
    if settings.teams_app_id and settings.teams_app_password:
        from ..connectors.teams import SERVICE_HOSTS, BotConnector, TeamsWhisperChannel

        teams_connector = BotConnector(settings.teams_app_id, settings.teams_app_password,
                                       tenant_id=settings.teams_tenant_id,
                                       service_hosts=settings.teams_service_hosts or SERVICE_HOSTS)
        channels.append(TeamsWhisperChannel(name="teams-whispers", connector=teams_connector,
                                            public_url=settings.public_url))
    return slack_api, teams_connector, channels


def connect_directories(channels: list[Any], repository: Any) -> None:
    """Channels that find people through the repository (Teams) get it here."""
    for channel in channels:
        if hasattr(channel, "directory"):
            channel.directory = repository.chat_identity


def build_repository(settings: ServerSettings, *, chat_channels: list[Any] | None = None,
                     migrate: bool | None = None) -> Any:
    """The SQL repository with every configured notification channel. ``migrate`` overrides
    ``METIS_MIGRATE_ON_START``."""
    from ..notify import Notifier, load_channels
    from ..storage.sql import SqlRepository

    if chat_channels is None:
        chat_channels = chat_integrations(settings)[2]
    channels, public_url = load_channels()
    repository = SqlRepository(
        settings.database_url, cache_size=settings.engine_cache_size,
        engine_options=settings.engine_options(),
        notifier=Notifier(channels + chat_channels, public_url=public_url or settings.public_url),
        migrate=settings.migrate_on_start if migrate is None else migrate,
        lock_timeout=settings.lock_timeout_seconds,
        statement_timeout=settings.statement_timeout_seconds,
        pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
        app_role=settings.db_app_role)
    connect_directories(chat_channels, repository)
    return repository
