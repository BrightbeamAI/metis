"""CHAP artefact construction (chap-task.schema.json, Artefact definition).

CHAP allows implementations to add artefact kinds with a ``schema`` reference. All
Metis artefact kinds (``tacit.*``) are declared this way; ``capture_fragment`` is a
standard CHAP kind we also honour.
"""
from __future__ import annotations

from typing import Any

from chap_coordinator import content_hash

SCHEMA_BASE = "https://metis.dev/schemas/0.1"
STANDARD_KINDS = {
    "draft",
    "decision",
    "override",
    "abstention",
    "escalation",
    "citation_set",
    "snapshot",
    "capture_fragment",
    "route_decision",
}


def schema_uri_for(kind: str) -> str | None:
    """Return a schema URI for non-standard (tacit.*) artefact kinds."""
    if kind in STANDARD_KINDS:
        return None
    slug = kind.replace(".", "_")
    return f"{SCHEMA_BASE}/{slug}.schema.json"


def to_chap_canonical(value: Any) -> Any:
    """Make a JSON value safe for CHAP's canonical form (chap-coordinator >= 0.2.9).

    CHAP canonical numbers must be integers; decimals are represented as strings
    (for example ``0.3`` becomes ``"0.3"``) so hashes are deterministic across
    implementations. Metis domain models keep native floats; this conversion is
    applied only at the CHAP boundary.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else str(value)
    if isinstance(value, dict):
        return {k: to_chap_canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_chap_canonical(v) for v in value]
    return value


def build_artefact(
    *,
    artefact_id: str,
    kind: str,
    produced_by: str,
    produced_at: str,
    content: Any,
    task: str | None = None,
    based_on: str | None = None,
    logical_id: str | None = None,
    tags: list[str] | None = None,
    routing_hints: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = to_chap_canonical(content)
    art: dict[str, Any] = {
        "id": artefact_id,
        "kind": kind,
        "produced_by": produced_by,
        "produced_at": produced_at,
        "content": content,
        "content_hash": content_hash(content),
    }
    schema = schema_uri_for(kind)
    if schema:
        art["schema"] = schema
    if task:
        art["task"] = task
    if based_on:
        art["based_on"] = based_on
    if logical_id:
        art["logical_id"] = logical_id
    if tags:
        art["tags"] = tags
    if routing_hints:
        art["routing_hints"] = routing_hints
    if citations:
        art["citations"] = citations
    if metadata:
        art["metadata"] = metadata
    return art
