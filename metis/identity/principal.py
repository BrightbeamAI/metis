"""The authenticated caller of a Metis server."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..integrations.chap.participants import type_of, validate_uri

# Roles that hold across workspaces. Workspace roles (worker, reviewer, ...) come from the
# workspace's membership. ``metrics`` reads only the server's counts (a monitoring scraper).
GLOBAL_ROLES = frozenset({"admin", "auditor", "metrics"})


class AuthenticationError(Exception):
    """The request's credentials are missing, malformed, expired, or unknown."""


class IdentityProviderUnavailable(Exception):
    """The identity provider's keys could not be fetched, so no token can be checked now."""


def global_roles_allowed(uri: str, roles: frozenset[str] | set[str] | tuple[str, ...]) -> None:
    """Raise ``ValueError`` when ``uri`` may not hold ``roles``: admin is for people, auditor
    for people and services."""
    kind = type_of(uri)
    if "admin" in roles and kind != "human":
        raise ValueError(f"{uri}: the global admin role is for people (human:...).")
    if "auditor" in roles and kind not in ("human", "service"):
        raise ValueError(f"{uri}: the global auditor role is for people and services.")
    if "metrics" in roles and kind not in ("human", "service"):
        raise ValueError(f"{uri}: the global metrics role is for people and services.")


@dataclass(frozen=True)
class Principal:
    """Who is calling: the identity Metis records as a CHAP participant URI.

    ``global_roles`` may hold ``admin`` (create workspaces and manage their members; people
    only) and ``auditor`` (read every workspace's evidence; people and services). They grant no
    workspace role: an admin who reviews fragments is also a reviewer member of that workspace.
    """

    uri: str
    subject: str
    method: str
    display_name: str | None = None
    issuer: str | None = None
    global_roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        validate_uri(self.uri)
        unknown = set(self.global_roles) - GLOBAL_ROLES
        if unknown:
            raise ValueError(f"Unknown global roles: {', '.join(sorted(unknown))}")

    @property
    def kind(self) -> str:
        return type_of(self.uri)

    @property
    def is_admin(self) -> bool:
        """Global admin: held only by people, whatever a credential claims."""
        return "admin" in self.global_roles and self.kind == "human"

    @property
    def is_auditor(self) -> bool:
        """Global auditor: held by people and services, never by agents, which must not read
        Evidence-layer fragments."""
        return ("auditor" in self.global_roles and self.kind in ("human", "service")) or self.is_admin

    @property
    def reads_metrics(self) -> bool:
        """May read the server's counts (``/metrics``): the metrics role, or global auditor."""
        return ("metrics" in self.global_roles and self.kind in ("human", "service")) \
            or self.is_auditor
