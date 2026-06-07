"""CHAP integration layer, TacitFlow's protocol foundation (a faithful Python adapter).

CHAP itself is defined by the supplied specification, schemas, and TypeScript reference.
This package emits and validates CHAP-compatible workspaces, participants, tasks,
artefacts, whisper/review/routing/control/handoff events, and an append-only Ed25519+JCS
evidence chain. It does not reimplement CHAP as a new protocol.
"""
from .adapter import CHAPAdapter
from .canonical import ZERO_HASH, canonicalize, content_hash, sha256_hex
from .evidence import EvidenceChain, EvidenceEntry
from .ids import IdFactory

__all__ = [
    "CHAPAdapter",
    "EvidenceChain",
    "EvidenceEntry",
    "IdFactory",
    "canonicalize",
    "content_hash",
    "sha256_hex",
    "ZERO_HASH",
]
