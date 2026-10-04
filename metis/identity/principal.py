"""The authenticated caller of a Metis server."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..integrations.chap.participants import type_of, validate_uri

# Roles that hold across workspaces. Workspace roles (worker, reviewer, ...) come from the
# workspace's membership.
GLOBAL_ROLES = frozenset({"admin", "auditor"})


class AuthenticationError(Exception):
    """The request's credentials are missing, malformed, expired, or unknown."""


@dataclass(frozen=True)
class Principal:
    """Who is calling: the identity Metis records as a CHAP participant URI.

    ``global_roles`` may hold ``admin`` (create workspaces and manage their members) and
    ``auditor`` (read every workspace's evidence). They grant no workspace role: an admin who
    reviews fragments is also a reviewer member of that workspace.
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
        return "admin" in self.global_roles

    @property
    def is_auditor(self) -> bool:
        return "auditor" in self.global_roles or self.is_admin
