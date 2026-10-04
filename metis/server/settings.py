"""Server configuration, read from ``METIS_*`` environment variables.

Sign-in is configured by any combination of OIDC (``METIS_OIDC_ISSUER`` and
``METIS_OIDC_AUDIENCE``), API keys (``METIS_API_KEYS_FILE``), and a trusted proxy
(``METIS_TRUSTED_PROXY_SECRET``). The server refuses to start with none of them.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..identity import (
    ApiKeyAuthenticator,
    Authenticator,
    AuthenticatorChain,
    OIDCAuthenticator,
    TrustedHeaderAuthenticator,
)


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").replace(";", ",").split(",") if v.strip()]


def _flag(value: str | None, name: str = "setting", default: bool = False) -> bool:
    """A yes/no variable; anything but true/false, yes/no, on/off, or 1/0 is refused."""
    text = (value or "").strip().lower()
    if not text:
        return default
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be true or false, not {value!r}.")


class ServerSettings(BaseModel):
    database_url: str = "sqlite:///./.metis/server.db"
    # OIDC
    oidc_issuer: str | None = None
    oidc_audience: list[str] = Field(default_factory=list)
    oidc_jwks_url: str | None = None
    oidc_jwks_file: str | None = None
    oidc_roles_claim: str = "roles"
    oidc_email_claim: str = "email"
    oidc_name_claim: str = "name"
    oidc_participant_claim: str | None = None
    oidc_require_email_verified: bool = False
    oidc_admin_role: str = "metis-admin"
    oidc_auditor_role: str = "metis-auditor"
    # API keys and a trusted proxy
    api_keys_file: str | None = None
    trusted_proxy_secret: str | None = None
    trusted_proxy_email_header: str = "X-Forwarded-Email"
    trusted_proxy_groups_header: str = "X-Forwarded-Groups"
    # Administration and behaviour
    admins: list[str] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=list)
    whisper_deadline_hours: int = 168
    escalation_grant_hours: float = Field(12.0, ge=0)
    use_live_model: bool = False
    model_url: str | None = None
    model_name: str | None = None
    engine_cache_size: int = 64
    log_level: str = "info"
    # Storage and limits
    migrate_on_start: bool = True
    lock_timeout_seconds: float = Field(30.0, gt=0, le=3600)
    statement_timeout_seconds: float = Field(60.0, gt=0, le=86400)
    db_pool_size: int = Field(5, ge=1)
    db_max_overflow: int = Field(10, ge=0)
    db_app_role: str | None = None
    max_body_bytes: int = Field(4 * 1024 * 1024, ge=1024)
    outbox_retention_days: int = Field(30, ge=1)
    api_docs: bool = False
    # Background work, people's links, and the web app
    public_url: str | None = None
    sweep_interval_seconds: int = 300
    dispatch_interval_seconds: int = 5
    ui_client_id: str | None = None
    ui_scopes: str = "openid profile email"
    remote_mcp: bool = True
    connectors_file: str | None = None
    # Whispers in chat tools
    slack_bot_token: str | None = None
    slack_signing_secret: str | None = None
    teams_app_id: str | None = None
    teams_app_password: str | None = None
    teams_tenant_id: str | None = None
    teams_allowed_tenants: list[str] = Field(default_factory=list)
    teams_service_hosts: list[str] = Field(default_factory=list)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServerSettings:
        env = os.environ if env is None else env
        values: dict[str, Any] = {
            "database_url": env.get("METIS_DATABASE_URL"),
            "oidc_issuer": env.get("METIS_OIDC_ISSUER"),
            "oidc_audience": _split(env.get("METIS_OIDC_AUDIENCE")),
            "oidc_jwks_url": env.get("METIS_OIDC_JWKS_URL"),
            "oidc_jwks_file": env.get("METIS_OIDC_JWKS_FILE"),
            "oidc_roles_claim": env.get("METIS_OIDC_ROLES_CLAIM"),
            "oidc_email_claim": env.get("METIS_OIDC_EMAIL_CLAIM"),
            "oidc_name_claim": env.get("METIS_OIDC_NAME_CLAIM"),
            "oidc_participant_claim": env.get("METIS_OIDC_PARTICIPANT_CLAIM"),
            "oidc_require_email_verified": _flag(env.get("METIS_OIDC_REQUIRE_EMAIL_VERIFIED"),
                                                 "METIS_OIDC_REQUIRE_EMAIL_VERIFIED"),
            "oidc_admin_role": env.get("METIS_OIDC_ADMIN_ROLE"),
            "oidc_auditor_role": env.get("METIS_OIDC_AUDITOR_ROLE"),
            "api_keys_file": env.get("METIS_API_KEYS_FILE"),
            "trusted_proxy_secret": env.get("METIS_TRUSTED_PROXY_SECRET"),
            "trusted_proxy_email_header": env.get("METIS_TRUSTED_PROXY_EMAIL_HEADER"),
            "trusted_proxy_groups_header": env.get("METIS_TRUSTED_PROXY_GROUPS_HEADER"),
            "admins": _split(env.get("METIS_ADMINS")),
            "cors_origins": _split(env.get("METIS_CORS_ORIGINS")),
            "whisper_deadline_hours": env.get("METIS_WHISPER_DEADLINE_HOURS"),
            "escalation_grant_hours": env.get("METIS_ESCALATION_GRANT_HOURS"),
            "use_live_model": _flag(env.get("METIS_USE_LIVE_MODEL"), "METIS_USE_LIVE_MODEL"),
            "model_url": env.get("METIS_MODEL_URL"),
            "model_name": env.get("METIS_MODEL_NAME"),
            "engine_cache_size": env.get("METIS_ENGINE_CACHE_SIZE"),
            "migrate_on_start": _flag(env.get("METIS_MIGRATE_ON_START"), "METIS_MIGRATE_ON_START",
                                      default=True),
            "lock_timeout_seconds": env.get("METIS_LOCK_TIMEOUT_SECONDS"),
            "statement_timeout_seconds": env.get("METIS_STATEMENT_TIMEOUT_SECONDS"),
            "db_pool_size": env.get("METIS_DB_POOL_SIZE"),
            "db_max_overflow": env.get("METIS_DB_MAX_OVERFLOW"),
            "db_app_role": env.get("METIS_DB_APP_ROLE"),
            "max_body_bytes": env.get("METIS_MAX_BODY_BYTES"),
            "outbox_retention_days": env.get("METIS_OUTBOX_RETENTION_DAYS"),
            "api_docs": _flag(env.get("METIS_API_DOCS"), "METIS_API_DOCS"),
            "log_level": env.get("METIS_LOG_LEVEL"),
            "public_url": env.get("METIS_PUBLIC_URL"),
            "sweep_interval_seconds": env.get("METIS_SWEEP_INTERVAL_SECONDS"),
            "dispatch_interval_seconds": env.get("METIS_DISPATCH_INTERVAL_SECONDS"),
            "ui_client_id": env.get("METIS_UI_CLIENT_ID"),
            "ui_scopes": env.get("METIS_UI_SCOPES"),
            "remote_mcp": _flag(env.get("METIS_REMOTE_MCP"), "METIS_REMOTE_MCP", default=True),
            "connectors_file": env.get("METIS_CONNECTORS_FILE"),
            "slack_bot_token": env.get("METIS_SLACK_BOT_TOKEN"),
            "slack_signing_secret": env.get("METIS_SLACK_SIGNING_SECRET"),
            "teams_app_id": env.get("METIS_TEAMS_APP_ID"),
            "teams_app_password": env.get("METIS_TEAMS_APP_PASSWORD"),
            "teams_tenant_id": env.get("METIS_TEAMS_TENANT_ID"),
            "teams_allowed_tenants": _split(env.get("METIS_TEAMS_ALLOWED_TENANTS")),
            "teams_service_hosts": _split(env.get("METIS_TEAMS_SERVICE_HOSTS")),
        }
        return cls(**{k: v for k, v in values.items() if v not in (None, "")})

    @property
    def whisper_deadline_ms(self) -> int:
        return int(self.whisper_deadline_hours) * 60 * 60 * 1000

    @property
    def teams_tenants(self) -> list[str]:
        """The Microsoft Entra tenants whose people may use the Teams bot."""
        return sorted(set(self.teams_allowed_tenants) | ({self.teams_tenant_id}
                                                         if self.teams_tenant_id else set()))

    def check_integrations(self) -> None:
        """Refuse a chat integration that is only half configured, or open to any tenant."""
        if bool(self.slack_bot_token) != bool(self.slack_signing_secret):
            raise ValueError("Slack needs both METIS_SLACK_BOT_TOKEN and "
                             "METIS_SLACK_SIGNING_SECRET: the token sends whispers, and the "
                             "signing secret verifies the answers.")
        if bool(self.teams_app_id) != bool(self.teams_app_password):
            raise ValueError("Teams needs both METIS_TEAMS_APP_ID and METIS_TEAMS_APP_PASSWORD.")
        if self.teams_app_id and not self.teams_tenants:
            raise ValueError("Name the Microsoft Entra tenants whose people may use the Teams bot: "
                             "METIS_TEAMS_TENANT_ID, or METIS_TEAMS_ALLOWED_TENANTS for several.")

    def engine_options(self) -> dict[str, Any]:
        """Options for every workspace engine: the local model (whether to use it, and where it
        runs), and how long a person's decision on an escalation holds."""
        options: dict[str, Any] = {"use_live_model": self.use_live_model,
                                   "escalation_grant_hours": self.escalation_grant_hours}
        if self.model_url or self.model_name:
            from ..models.model_config import ModelConfig

            base = ModelConfig()
            options["model_config"] = base.model_copy(update={
                k: v for k, v in (("url", self.model_url), ("name", self.model_name)) if v})
        return options

    def authenticators(self) -> list[Authenticator]:
        found: list[Authenticator] = []
        if self.oidc_issuer:
            if not self.oidc_audience:
                raise ValueError("METIS_OIDC_ISSUER is set; set METIS_OIDC_AUDIENCE too.")
            jwks = (json.loads(Path(self.oidc_jwks_file).read_text(encoding="utf-8"))
                    if self.oidc_jwks_file else None)
            audience = self.oidc_audience[0] if len(self.oidc_audience) == 1 else self.oidc_audience
            found.append(OIDCAuthenticator(
                issuer=self.oidc_issuer, audience=audience, jwks_url=self.oidc_jwks_url,
                jwks=jwks, roles_claim=self.oidc_roles_claim, email_claim=self.oidc_email_claim,
                name_claim=self.oidc_name_claim, participant_claim=self.oidc_participant_claim,
                admin_role=self.oidc_admin_role, auditor_role=self.oidc_auditor_role,
                require_email_verified=self.oidc_require_email_verified))
        if self.api_keys_file:
            found.append(ApiKeyAuthenticator.from_file(self.api_keys_file))
        if self.trusted_proxy_secret:
            found.append(TrustedHeaderAuthenticator(
                secret=self.trusted_proxy_secret, email_header=self.trusted_proxy_email_header,
                groups_header=self.trusted_proxy_groups_header,
                admin_group=self.oidc_admin_role, auditor_group=self.oidc_auditor_role))
        return found

    def authenticator(self) -> AuthenticatorChain:
        found = self.authenticators()
        if not found:
            raise ValueError(
                "Configure sign-in: METIS_OIDC_ISSUER and METIS_OIDC_AUDIENCE, "
                "METIS_API_KEYS_FILE, or METIS_TRUSTED_PROXY_SECRET.")
        return AuthenticatorChain(found, admins=self.admins)
