"""The workspace repository: how a Metis server stores and serialises its workspaces.

A repository owns every workspace's persistent state and guarantees one writer per workspace.
``write`` runs a function against the workspace's engine and commits everything it recorded
(domain state, the CHAP chain, and the evidence ledger) together, or nothing. ``read`` runs a
function against the committed state and records nothing.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from ..engine import MetisEngine
    from ..governance.membership import Member

T = TypeVar("T")

WORKSPACE_ID_RE = re.compile(r"^wsp_[a-z0-9][a-z0-9_-]{0,62}$")
ESCALATION_GROUP = "group:escalation@metis.local"
DEFAULT_WHISPER_DEADLINE_MS = 7 * 24 * 60 * 60 * 1000  # a week


class UnknownWorkspace(KeyError):
    """No workspace with this id, or none the caller has ever been part of."""

    def __init__(self, workspace_id: str) -> None:
        super().__init__(f"No workspace {workspace_id}.")
        self.workspace_id = workspace_id


class WorkspaceExists(ValueError):
    """A workspace with this id already exists."""


class WorkspaceConflict(RuntimeError):
    """Another writer changed the workspace first; the operation can be retried."""


class WorkspaceBusy(RuntimeError):
    """The workspace's writer lock was not free in time; try again shortly."""


class StorageCorruption(RuntimeError):
    """Stored state is inconsistent, for example the CHAP chain and the ledger disagree."""


class SchemaTooNew(RuntimeError):
    """The database, or a workspace in it, was written by a newer Metis than this one."""


@dataclass
class WorkspaceSettings:
    """What a new workspace is created with."""

    id: str
    name: str
    site: str = "site"
    review_rule: str = "quorum:2"
    whisper_deadline_ms: int = DEFAULT_WHISPER_DEADLINE_MS
    escalation_assignee: str = ESCALATION_GROUP
    members: list[Member] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not WORKSPACE_ID_RE.match(self.id):
            raise ValueError("A workspace id starts with wsp_ and uses lowercase letters, digits, "
                             f"hyphens, and underscores (at most 66 characters): {self.id!r}")
        if not self.name.strip():
            raise ValueError("A workspace needs a name")
        if self.whisper_deadline_ms < 60_000:
            raise ValueError("whisper_deadline_ms must be at least a minute")


@dataclass(frozen=True)
class WorkspaceSummary:
    id: str
    name: str
    site: str
    created_at: str
    updated_at: str
    version: int


class WorkspaceRepository(Protocol):
    def migrate(self) -> int: ...

    def create(self, settings: WorkspaceSettings, *, by: str) -> dict[str, Any]: ...

    def list(self) -> list[WorkspaceSummary]: ...

    def exists(self, workspace_id: str) -> bool: ...

    def memberships(self, uri: str) -> dict[str, list[str]]: ...

    def member_roles(self, workspace_id: str, uri: str) -> list[str] | None: ...

    def write(self, workspace_id: str, fn: Callable[[MetisEngine], T]) -> T: ...

    def read(self, workspace_id: str, fn: Callable[[MetisEngine], T]) -> T: ...

    def ping(self) -> bool: ...

    def close(self) -> None: ...
