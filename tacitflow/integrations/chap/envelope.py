"""CHAP envelope construction and signing.

An envelope is the wire object wrapping every CHAP message:
``chap, id, ts, workspace, from, to, type, method, params, evidence{prev_hash, sig}``.
We build envelopes as plain dicts so the JCS canonicalisation is faithful.
"""
from __future__ import annotations

import copy
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .canonical import canonicalize, sha256_hex
from .crypto import sign

CHAP_WIRE_VERSION = "0.2"


def build_envelope(
    *,
    envelope_id: str,
    ts: str,
    workspace: str,
    sender: str,
    to: str | list[str],
    method: str,
    params: dict[str, Any],
    prev_hash: str,
    msg_type: str = "request",
) -> dict[str, Any]:
    """Build an unsigned envelope dict with ``evidence.prev_hash`` set."""
    return {
        "chap": CHAP_WIRE_VERSION,
        "id": envelope_id,
        "ts": ts,
        "workspace": workspace,
        "from": sender,
        "to": to,
        "type": msg_type,
        "method": method,
        "params": params,
        "evidence": {"prev_hash": prev_hash, "sig": None},
    }


def canonical_without_sig(envelope: dict[str, Any]) -> bytes:
    """JCS canonical bytes of the envelope with ``evidence.sig`` removed."""
    env = copy.deepcopy(envelope)
    env.get("evidence", {}).pop("sig", None)
    return canonicalize(env)


def envelope_hash(envelope: dict[str, Any]) -> str:
    return sha256_hex(canonical_without_sig(envelope))


def sign_envelope(envelope: dict[str, Any], key: Ed25519PrivateKey) -> tuple[dict[str, Any], bytes]:
    """Sign an envelope in place; return (signed_envelope, canonical_bytes_without_sig)."""
    canonical = canonical_without_sig(envelope)
    signature = sign(canonical, key)
    envelope["evidence"]["sig"] = signature
    return envelope, canonical
