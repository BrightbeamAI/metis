"""CHAP integration layer.

TacitFlow runs on the official ``chap-coordinator`` reference implementation. This package
adapts TacitFlow's domain onto a real Coordinator and exposes the canonical CHAP primitives.
It does not reimplement the protocol.
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
