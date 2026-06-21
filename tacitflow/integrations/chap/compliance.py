"""Compliance checks against the official CHAP reference implementation.

These assert that what TacitFlow emits are valid JSON-RPC envelopes using only methods the
``chap-coordinator`` reference implements, and that artefacts follow CHAP conventions. The
method allow-list is read directly from the Coordinator, so it cannot drift: if TacitFlow
ever dispatched a method the reference does not implement, the dispatch would error and never
be audited in the first place.
"""
from __future__ import annotations

import re
from typing import Any

from chap_coordinator import Coordinator

from .canonical import content_hash

# The authoritative method set is whatever the reference Coordinator implements.
COORDINATOR_METHODS: set[str] = set(Coordinator()._handlers.keys())
# Backwards-compatible alias used by older tests.
CHAP_METHODS = COORDINATOR_METHODS

ENVELOPE_KEYS = {"jsonrpc", "id", "method", "params", "result", "error"}
_ULID = r"[0-9A-HJKMNP-TV-Z]{26}"
_RE_ART = re.compile(rf"^art_{_ULID}$")
_RE_METHOD = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_RE_URI = re.compile(r"^(human|agent|service|group|workspace):[^\s]+$")
_RE_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")


class ComplianceError(ValueError):
    pass


def assert_no_custom_protocol(envelope: dict[str, Any]) -> None:
    """Fail if the envelope adds protocol-level keys CHAP/JSON-RPC does not define, or a
    method the reference Coordinator does not implement."""
    extra = set(envelope) - ENVELOPE_KEYS
    if extra:
        raise ComplianceError(f"Envelope introduces non-CHAP top-level keys: {sorted(extra)}")
    method = envelope.get("method")
    if method is not None and method not in COORDINATOR_METHODS:
        raise ComplianceError(f"Envelope uses a method the reference Coordinator does not implement: {method!r}")


def validate_envelope(envelope: dict[str, Any]) -> None:
    if envelope.get("jsonrpc") != "2.0":
        raise ComplianceError("Envelope is not JSON-RPC 2.0")
    method = envelope.get("method")
    if not isinstance(method, str) or not _RE_METHOD.match(method):
        raise ComplianceError(f"Bad or missing method: {method!r}")
    if not isinstance(envelope.get("params"), dict):
        raise ComplianceError("Envelope params must be an object")
    assert_no_custom_protocol(envelope)


def validate_artefact(artefact: dict[str, Any]) -> None:
    for field in ("id", "kind", "produced_by", "produced_at", "content_hash"):
        if field not in artefact:
            raise ComplianceError(f"Artefact missing required field: {field}")
    if not _RE_ART.match(artefact["id"]):
        raise ComplianceError(f"Bad artefact id: {artefact['id']}")
    if not _RE_URI.match(artefact["produced_by"]):
        raise ComplianceError(f"Bad produced_by URI: {artefact['produced_by']}")
    if not _RE_SHA.match(artefact["content_hash"]):
        raise ComplianceError("content_hash malformed")
    if "content" in artefact and content_hash(artefact["content"]) != artefact["content_hash"]:
        raise ComplianceError("content_hash does not match content")
    if artefact["kind"].startswith("tacit.") and "schema" not in artefact:
        raise ComplianceError(f"Custom artefact kind {artefact['kind']} lacks a schema reference")


def validate_evidence_record(rec: dict[str, Any]) -> None:
    for field in ("seq", "workspace", "method_or_type", "envelope"):
        if field not in rec:
            raise ComplianceError(f"Evidence entry missing required field: {field}")
    if not isinstance(rec["envelope"], dict):
        raise ComplianceError("Evidence entry envelope must be an object")
    if rec.get("prev_hash") is not None and not _RE_SHA.match(rec["prev_hash"]):
        raise ComplianceError("evidence prev_hash malformed")
    validate_envelope(rec["envelope"])
