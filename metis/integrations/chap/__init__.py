"""CHAP integration layer.

Metis drives the official ``chap-coordinator`` reference implementation. This package
adapts Metis's domain onto a real Coordinator and re-exports the canonical CHAP primitives
(canonical JSON, hashing, identifiers) from it.
"""
from chap_coordinator import ZERO_HASH, IdFactory, canonicalize, content_hash, sha256_hex

from .adapter import ChainView, CHAPAdapter, VerificationResult

__all__ = [
    "CHAPAdapter",
    "ChainView",
    "VerificationResult",
    "IdFactory",
    "canonicalize",
    "content_hash",
    "sha256_hex",
    "ZERO_HASH",
]
