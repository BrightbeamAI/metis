"""JCS canonicalisation and hashing.

Re-exported from the official ``chap-coordinator`` reference implementation so TacitFlow
uses the canonical CHAP primitives rather than its own copy.
"""
from __future__ import annotations

from chap_coordinator import ZERO_HASH, canonicalize, content_hash, sha256_hex

__all__ = ["ZERO_HASH", "canonicalize", "content_hash", "sha256_hex"]
