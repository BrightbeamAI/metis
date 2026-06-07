"""Compliance checks against CHAP conventions.

These functions assert that what TacitFlow emits conforms to the supplied CHAP schemas
and method catalogue, and, crucially, that TacitFlow has NOT invented its own protocol
envelope or methods. ``tacit.*`` identifiers appear only as artefact *kinds* and task
*kinds* (declared by the tacitflow/1.0 profile), never as new CHAP envelope methods.
"""
from __future__ import annotations

import re
from typing import Any

from .canonical import content_hash

# Methods drawn from the CHAP v0.2 method catalogue (schemas/profiles/chap-methods.schema.json).
CHAP_METHODS: set[str] = {
    # core
    "workspace.create", "workspace.describe", "workspace.set_profiles", "workspace.close",
    "participant.join", "participant.leave", "task.create", "task.update", "task.complete",
    "capture.append", "audit.read", "audit.export", "notify.message", "notify.alert",
    # review/1.0
    "review.request", "review.acknowledge", "decide.approve", "decide.reject",
    "decide.override", "abstain.declare", "escalate.raise",
    # whisper/1.0
    "whisper.ask", "whisper.answer",
    # routing/1.0
    "task.route", "review.depth", "escalate.auto",
    # control/1.0
    "control.pause", "control.resume", "control.cancel", "control.supersede",
    "control.snapshot", "control.rollback",
    # handoff/1.0
    "handoff.propose", "handoff.accept", "handoff.decline",
}

ENVELOPE_KEYS = {
    "chap", "id", "ts", "workspace", "from", "to", "type",
    "method", "params", "result", "error", "evidence", "correlation_id", "reply_to",
}
_ULID = r"[0-9A-HJKMNP-TV-Z]{26}"
_RE_ID = re.compile(rf"^{_ULID}$")
_RE_WSP = re.compile(r"^wsp_[A-Za-z0-9_-]+$")
_RE_ART = re.compile(rf"^art_{_ULID}$")
_RE_TSK = re.compile(rf"^tsk_{_ULID}$")
_RE_METHOD = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_RE_URI = re.compile(r"^(human|agent|service|group|workspace):[^\s]+$")
_RE_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_RE_SIG = re.compile(r"^ed25519:([A-Za-z0-9._-]+:)?[A-Za-z0-9+/=]+$")


class ComplianceError(ValueError):
    pass


def assert_no_custom_protocol(envelope: dict[str, Any]) -> None:
    """Fail if the envelope introduces protocol-level keys CHAP does not define, or a
    method outside the CHAP catalogue."""
    extra = set(envelope) - ENVELOPE_KEYS
    if extra:
        raise ComplianceError(f"Envelope introduces non-CHAP top-level keys: {sorted(extra)}")
    method = envelope.get("method")
    if method is not None and method not in CHAP_METHODS:
        raise ComplianceError(f"Envelope uses a method outside the CHAP catalogue: {method!r}")


def validate_envelope(envelope: dict[str, Any]) -> None:
    for field in ("chap", "id", "ts", "workspace", "from", "to", "type", "evidence"):
        if field not in envelope:
            raise ComplianceError(f"Envelope missing required field: {field}")
    if not _RE_ID.match(envelope["id"]):
        raise ComplianceError(f"Bad envelope id: {envelope['id']}")
    if not _RE_WSP.match(envelope["workspace"]):
        raise ComplianceError(f"Bad workspace id: {envelope['workspace']}")
    if not _RE_URI.match(envelope["from"]):
        raise ComplianceError(f"Bad from URI: {envelope['from']}")
    if envelope["type"] not in ("request", "response", "notification"):
        raise ComplianceError(f"Bad envelope type: {envelope['type']}")
    if envelope["type"] in ("request", "notification"):
        if not _RE_METHOD.match(envelope.get("method", "")):
            raise ComplianceError("request/notification requires a valid method")
        if "params" not in envelope:
            raise ComplianceError("request/notification requires params")
    ev = envelope["evidence"]
    if not _RE_SHA.match(ev.get("prev_hash", "")):
        raise ComplianceError("evidence.prev_hash malformed")
    if ev.get("sig") is not None and not _RE_SIG.match(ev["sig"]):
        raise ComplianceError("evidence.sig malformed")
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
    # Non-standard (tacit.*) kinds MUST carry a schema reference per CHAP.
    if artefact["kind"].startswith("tacit.") and "schema" not in artefact:
        raise ComplianceError(f"Custom artefact kind {artefact['kind']} lacks a schema reference")


def validate_evidence_record(rec: dict[str, Any]) -> None:
    for field in ("seq", "workspace", "envelope_hash", "prev_hash", "sig", "from", "ts", "method_or_type"):
        if field not in rec:
            raise ComplianceError(f"Evidence entry missing required field: {field}")
    if not _RE_SHA.match(rec["envelope_hash"]) or not _RE_SHA.match(rec["prev_hash"]):
        raise ComplianceError("evidence hashes malformed")
    if not _RE_SIG.match(rec["sig"]):
        raise ComplianceError("evidence sig malformed")
