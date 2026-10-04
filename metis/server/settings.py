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


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


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
    oidc_participant_claim: str = "metis_participant"
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
    use_live_model: bool = False
    engine_cache_size: int = 64
    log_level: str = "info"

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
            "oidc_admin_role": env.get("METIS_OIDC_ADMIN_ROLE"),
            "oidc_auditor_role": env.get("METIS_OIDC_AUDITOR_ROLE"),
            "api_keys_file": env.get("METIS_API_KEYS_FILE"),
            "trusted_proxy_secret": env.get("METIS_TRUSTED_PROXY_SECRET"),
            "trusted_proxy_email_header": env.get("METIS_TRUSTED_PROXY_EMAIL_HEADER"),
            "trusted_proxy_groups_header": env.get("METIS_TRUSTED_PROXY_GROUPS_HEADER"),
            "admins": _split(env.get("METIS_ADMINS")),
            "cors_origins": _split(env.get("METIS_CORS_ORIGINS")),
            "whisper_deadline_hours": env.get("METIS_WHISPER_DEADLINE_HOURS"),
            "use_live_model": _flag(env.get("METIS_USE_LIVE_MODEL")),
            "engine_cache_size": env.get("METIS_ENGINE_CACHE_SIZE"),
            "log_level": env.get("METIS_LOG_LEVEL"),
        }
        return cls(**{k: v for k, v in values.items() if v not in (None, "")})

    @property
    def whisper_deadline_ms(self) -> int:
        return int(self.whisper_deadline_hours) * 60 * 60 * 1000

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
                admin_role=self.oidc_admin_role, auditor_role=self.oidc_auditor_role))
        if self.api_keys_file:
            found.append(ApiKeyAuthenticator.from_file(self.api_keys_file))
        if self.trusted_proxy_secret:
            found.append(TrustedHeaderAuthenticator(
                secret=self.trusted_proxy_secret, email_header=self.trusted_proxy_email_header,
                groups_header=self.trusted_proxy_groups_header))
        return found

    def authenticator(self) -> AuthenticatorChain:
        found = self.authenticators()
        if not found:
            raise ValueError(
                "Configure sign-in: METIS_OIDC_ISSUER and METIS_OIDC_AUDIENCE, "
                "METIS_API_KEYS_FILE, or METIS_TRUSTED_PROXY_SECRET.")
        return AuthenticatorChain(found, admins=self.admins)
