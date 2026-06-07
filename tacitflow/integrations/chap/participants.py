"""CHAP participant URIs and descriptors.

Participant URI schemes: ``human:``, ``agent:``, ``service:``, ``group:``, ``workspace:``.
TacitFlow maps its roles onto these: operator -> human, whisperer -> agent,
Mission Group -> group, Runtime Orchestrator/Coordinator -> service.
"""
from __future__ import annotations

import re
from typing import Any

URI_RE = re.compile(r"^(human|agent|service|group|workspace):[^\s]+$")

VALID_TYPES = {"human", "agent", "service", "group", "workspace"}


def validate_uri(uri: str) -> str:
    if not URI_RE.match(uri):
        raise ValueError(f"Invalid participant URI: {uri!r}")
    return uri


def type_of(uri: str) -> str:
    return uri.split(":", 1)[0]


def participant_descriptor(
    uri: str,
    jwk: dict[str, Any],
    *,
    display_name: str | None = None,
    version: str | None = None,
    capabilities: dict[str, Any] | None = None,
    scopes: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a CHAP participant descriptor (chap-participant.schema.json)."""
    validate_uri(uri)
    desc: dict[str, Any] = {
        "uri": uri,
        "type": type_of(uri),
        "jwks": {"keys": [jwk]},
    }
    if display_name:
        desc["display_name"] = display_name
    if version:
        desc["version"] = version
    if capabilities:
        desc["capabilities"] = capabilities
    if scopes:
        desc["scopes"] = scopes
    if metadata:
        desc["metadata"] = metadata
    return desc
