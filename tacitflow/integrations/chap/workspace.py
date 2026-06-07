"""CHAP workspace descriptor construction (chap-workspace.schema.json)."""
from __future__ import annotations

from typing import Any

from .canonical import ZERO_HASH


def workspace_descriptor(
    *,
    workspace_id: str,
    name: str,
    created: str,
    coordinator: str,
    profiles: list[str],
    mode: str = "trial",
    mode_ceiling: str = "production",
    members: list[dict[str, Any]] | None = None,
    description: str | None = None,
    evidence_head: str = ZERO_HASH,
    evidence_count: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    desc: dict[str, Any] = {
        "id": workspace_id,
        "name": name,
        "created": created,
        "state": "active",
        "mode": mode,
        "mode_ceiling": mode_ceiling,
        "coordinator": coordinator,
        "members": members or [],
        "evidence_head": evidence_head,
        "evidence_count": evidence_count,
        "profiles": profiles,
    }
    if description:
        desc["description"] = description
    if metadata:
        desc["metadata"] = metadata
    return desc
