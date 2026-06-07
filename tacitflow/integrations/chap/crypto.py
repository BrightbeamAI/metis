"""Ed25519 signing for CHAP envelopes (RFC 8032), with deterministic demo keys.

Every CHAP message is signed with Ed25519 over the JCS canonicalisation of the
envelope with ``evidence.sig`` removed. For local demos and tests we derive a
participant's key deterministically from its URI, so the whole evidence chain is
reproducible without a key-management system. Production deployments supply real keys.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def derive_private_key(uri: str) -> Ed25519PrivateKey:
    """Deterministically derive a private key from a participant URI (demo/test use)."""
    seed = hashlib.sha256(("tacitflow:" + uri).encode("utf-8")).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_jwk(uri: str, key: Ed25519PrivateKey | None = None) -> dict:
    """Return the RFC 7517 JWK for a participant's public key."""
    key = key or derive_private_key(uri)
    raw = key.public_key().public_bytes_raw()
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "kid": hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16],
        "use": "sig",
        "alg": "EdDSA",
        "x": _b64url_nopad(raw),
    }


def sign(canonical_bytes: bytes, key: Ed25519PrivateKey) -> str:
    """Sign canonical bytes, returning a CHAP ``ed25519:<base64>`` signature string."""
    return "ed25519:" + _b64(key.sign(canonical_bytes))


def verify(canonical_bytes: bytes, sig: str, public_key: Ed25519PublicKey) -> bool:
    """Verify a CHAP signature string against canonical bytes."""
    if not sig.startswith("ed25519:"):
        return False
    raw = sig[len("ed25519:"):]
    # Allow an optional ed25519:<kid>:<sig> form.
    if raw.count(":") >= 1:
        raw = raw.split(":")[-1]
    try:
        public_key.verify(base64.b64decode(raw), canonical_bytes)
        return True
    except Exception:
        return False


class Keyring:
    """Holds participant signing keys. Deterministic by URI unless keys are injected."""

    def __init__(self) -> None:
        self._keys: dict[str, Ed25519PrivateKey] = {}

    def key_for(self, uri: str) -> Ed25519PrivateKey:
        if uri not in self._keys:
            self._keys[uri] = derive_private_key(uri)
        return self._keys[uri]

    def add(self, uri: str, key: Ed25519PrivateKey) -> None:
        self._keys[uri] = key

    def jwk(self, uri: str) -> dict:
        return public_jwk(uri, self.key_for(uri))
