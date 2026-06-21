"""Ed25519 signing and keys.

Re-exported from the official ``chap-coordinator`` reference implementation. Signing is used
by the security-signed/1.0 profile; TacitFlow's default chain is hash-linked (enable_chain).
"""
from __future__ import annotations

from chap_coordinator import Keyring, derive_private_key, public_jwk, sign, verify

__all__ = ["Keyring", "derive_private_key", "public_jwk", "sign", "verify"]
