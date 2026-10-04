"""Workspace membership: who may do what in a Metis workspace.

Each member is a CHAP participant holding one or more Metis roles, and the roles decide which
actions the member may take. The Mission Group is the set of members with the reviewer role.
Workers, reviewers, escalation handlers, and workspace admins are people; agents are software;
capture sources may be either. Every change to a member's roles is recorded on the
workspace's CHAP chain as a ``tacit.membership_record``.
"""
from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ..integrations.chap.participants import type_of, validate_uri


class Role(str, Enum):
    worker = "worker"
    reviewer = "reviewer"
    agent = "agent"
    capture = "capture"
    escalation = "escalation"
    auditor = "auditor"
    admin = "admin"


ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.worker: "answers whispers addressed to them, and inspects, contests, or withdraws "
                 "the fragments they contributed",
    Role.reviewer: "a Mission Group reviewer: votes on reviews and retires fragments",
    Role.agent: "receives governed guidance through the condition-aware gate",
    Role.capture: "submits observations of work for a named worker",
    Role.escalation: "decides retrievals that the gate hands to a person",
    Role.auditor: "reads fragments and the evidence chain",
    Role.admin: "manages the workspace's members",
}

# The participant types (CHAP URI schemes) each role admits.
ALLOWED_TYPES: dict[Role, frozenset[str]] = {
    Role.worker: frozenset({"human"}),
    Role.reviewer: frozenset({"human"}),
    Role.escalation: frozenset({"human"}),
    Role.admin: frozenset({"human"}),
    Role.auditor: frozenset({"human", "service"}),
    Role.agent: frozenset({"agent"}),
    Role.capture: frozenset({"agent", "service", "human"}),
}

# The role string a member joins the CHAP workspace with, from its first Metis role.
CHAP_ROLES: dict[Role, str] = {
    Role.worker: "operator",
    Role.reviewer: "mission_group_reviewer",
    Role.agent: "agent",
    Role.capture: "capture_source",
    Role.escalation: "escalation_handler",
    Role.auditor: "auditor",
    Role.admin: "workspace_admin",
}


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: str
    roles: list[Role] = Field(default_factory=list)
    display_name: str | None = None

    def has(self, role: Role | str) -> bool:
        return Role(role) in self.roles


class MembershipRecord(BaseModel):
    """The content of a ``tacit.membership_record``: one change to a member's roles."""

    model_config = ConfigDict(extra="forbid")

    participant: str
    roles: list[Role]
    granted: list[Role] = Field(default_factory=list)
    revoked: list[Role] = Field(default_factory=list)
    actioned_by: str
    reason: str | None = None


def check_roles(uri: str, roles: Iterable[Role | str]) -> list[Role]:
    """The roles as ``Role`` values, in a stable order, or ``ValueError``.

    A role must admit the participant's type: only people can be workers, reviewers,
    escalation handlers, or admins, and only agents can hold the agent role.
    """
    validate_uri(uri)
    kind = type_of(uri)
    wanted = {Role(r) for r in roles}
    for role in wanted:
        if kind not in ALLOWED_TYPES[role]:
            allowed = ", ".join(sorted(ALLOWED_TYPES[role]))
            raise ValueError(f"The {role.value} role admits {allowed} participants; {uri} is {kind}.")
    return [r for r in Role if r in wanted]


def demo_members(site: str) -> list[Member]:
    """The members of a demo workspace: one operator, three reviewers, and one agent."""
    return [
        Member(uri=f"human:operator@{site}", roles=[Role.worker, Role.escalation],
               display_name="Operator"),
        Member(uri="human:quality-lead@metis.local", roles=[Role.reviewer]),
        Member(uri="human:process-engineer@metis.local", roles=[Role.reviewer]),
        Member(uri="human:safety-officer@metis.local", roles=[Role.reviewer]),
        Member(uri="agent:assistant#v1", roles=[Role.agent]),
    ]
