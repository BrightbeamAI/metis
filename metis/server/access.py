"""Who may do what in a workspace, decided from the caller's roles.

Workspace roles come from the workspace's membership; the global admin and auditor roles come
from sign-in. A global role grants no workspace role: an administrator who reviews fragments is
also a reviewer member of that workspace.
"""
from __future__ import annotations

from typing import Any

from ..governance.lifecycle import contributed
from ..governance.membership import Role
from ..identity import Principal

# Roles that may read every fragment of a workspace.
FRAGMENT_READERS = {Role.reviewer, Role.auditor, Role.admin}


class Forbidden(PermissionError):
    """The caller is signed in but lacks the role this action needs."""


def roles_in(engine: Any, principal: Principal) -> set[Role]:
    return set(engine.roles_of(principal.uri))


def require(engine: Any, principal: Principal, *roles: Role, global_admin: bool = False,
            global_auditor: bool = False) -> set[Role]:
    """The caller's workspace roles, provided one of ``roles`` is among them (or a permitted
    global role applies); otherwise ``Forbidden``."""
    have = roles_in(engine, principal)
    if have & set(roles):
        return have
    if (global_admin and principal.is_admin) or (global_auditor and principal.is_auditor):
        return have
    names = " or ".join(r.value for r in roles)
    raise Forbidden(f"{principal.uri} needs the {names} role in {engine.adapter.workspace_id}.")


def require_member(engine: Any, principal: Principal) -> set[Role]:
    """Any workspace role, or the global admin or auditor role."""
    have = roles_in(engine, principal)
    if have or principal.is_auditor:
        return have
    raise Forbidden(f"{principal.uri} is not a member of {engine.adapter.workspace_id}.")




def can_read_fragment(engine: Any, principal: Principal, fragment: Any) -> bool:
    if roles_in(engine, principal) & FRAGMENT_READERS or principal.is_auditor:
        return True
    return contributed(fragment, principal.uri)


class ScopedRepository:
    """The workspace repository as one signed-in caller sees it.

    A workspace the caller has never been a member of looks exactly like one that does not
    exist, and is never loaded for them; a former member can still open it (a worker who left
    may withdraw consent for what they contributed). Global admins and auditors see every
    workspace. Everything else passes through to the repository.
    """

    def __init__(self, repo: Any, principal: Principal) -> None:
        self._repo = repo
        self.principal = principal

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repo, name)

    def _visible(self, workspace_id: str) -> None:
        p = self.principal
        if p.is_admin or p.is_auditor:
            return
        if self._repo.member_roles(workspace_id, p.uri) is None:
            from ..storage.repository import UnknownWorkspace

            raise UnknownWorkspace(workspace_id)

    def read(self, workspace_id: str, fn: Any) -> Any:
        self._visible(workspace_id)
        return self._repo.read(workspace_id, fn)

    def write(self, workspace_id: str, fn: Any, **kwargs: Any) -> Any:
        self._visible(workspace_id)
        return self._repo.write(workspace_id, fn, **kwargs)
