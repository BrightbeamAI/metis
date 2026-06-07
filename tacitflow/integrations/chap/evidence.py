"""Append-only, hash-linked CHAP evidence chain.

Implements the linkage from SPECIFICATION.md S10.1:

    entry_n.prev_hash = SHA-256( JCS(envelope_{n-1} without evidence.sig) || sig_{n-1} )

with the genesis entry using ``sha256:000...0``. Every accepted message produces exactly
one entry. The chain is never mutated; corrections and revocations are appended.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .canonical import ZERO_HASH, sha256_hex
from .crypto import derive_private_key, verify
from .envelope import canonical_without_sig, sign_envelope


def _link_hash(canonical_bytes: bytes, sig: str) -> str:
    """The value the *next* entry uses as its prev_hash."""
    return sha256_hex(canonical_bytes + sig.encode("utf-8"))


@dataclass
class EvidenceEntry:
    seq: int
    workspace: str
    envelope_hash: str
    prev_hash: str
    sig: str
    sender: str
    ts: str
    method_or_type: str
    envelope_id: str
    envelope: dict[str, Any] = field(repr=False, default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """The CHAP evidence-entry record (matches chap-evidence.schema.json)."""
        return {
            "seq": self.seq,
            "workspace": self.workspace,
            "envelope_hash": self.envelope_hash,
            "prev_hash": self.prev_hash,
            "sig": self.sig,
            "from": self.sender,
            "ts": self.ts,
            "method_or_type": self.method_or_type,
            "envelope_id": self.envelope_id,
        }


@dataclass
class VerificationResult:
    ok: bool
    checked: int
    errors: list[str] = field(default_factory=list)


class EvidenceChain:
    """A single workspace's append-only evidence chain."""

    def __init__(self, workspace: str) -> None:
        self.workspace = workspace
        self.entries: list[EvidenceEntry] = []
        self.head: str = ZERO_HASH
        self._link_of_head: str = ZERO_HASH

    @property
    def count(self) -> int:
        return len(self.entries)

    def append(self, envelope: dict[str, Any], key: Ed25519PrivateKey) -> EvidenceEntry:
        """Sign ``envelope`` (whose ``evidence.prev_hash`` must equal the current head
        link) and append the resulting evidence entry."""
        envelope["evidence"]["prev_hash"] = self._link_of_head
        signed, canonical = sign_envelope(envelope, key)
        sig = signed["evidence"]["sig"]
        method_or_type = signed.get("method") if signed["type"] != "response" else "response"
        entry = EvidenceEntry(
            seq=len(self.entries),
            workspace=self.workspace,
            envelope_hash=sha256_hex(canonical),
            prev_hash=self._link_of_head,
            sig=sig,
            sender=signed["from"],
            ts=signed["ts"],
            method_or_type=method_or_type or signed["type"],
            envelope_id=signed["id"],
            envelope=signed,
        )
        self.entries.append(entry)
        self._link_of_head = _link_hash(canonical, sig)
        self.head = entry.envelope_hash
        return entry

    def verify(self) -> VerificationResult:
        """Replay the chain and confirm signatures, links, monotonic ts, unique ids."""
        errors: list[str] = []
        expected_prev = ZERO_HASH
        last_ts_by_sender: dict[str, str] = {}
        seen_ids: set[str] = set()
        for entry in self.entries:
            canonical = canonical_without_sig(entry.envelope)
            if sha256_hex(canonical) != entry.envelope_hash:
                errors.append(f"seq {entry.seq}: envelope_hash mismatch")
            if entry.prev_hash != expected_prev:
                errors.append(f"seq {entry.seq}: prev_hash break")
            pub = derive_private_key(entry.sender).public_key()
            if not verify(canonical, entry.sig, pub):
                errors.append(f"seq {entry.seq}: signature does not verify")
            prior = last_ts_by_sender.get(entry.sender)
            if prior is not None and entry.ts < prior:
                errors.append(f"seq {entry.seq}: non-monotonic ts for {entry.sender}")
            last_ts_by_sender[entry.sender] = entry.ts
            if entry.envelope_id in seen_ids:
                errors.append(f"seq {entry.seq}: reused envelope id {entry.envelope_id}")
            seen_ids.add(entry.envelope_id)
            expected_prev = _link_hash(canonical, entry.sig)
        return VerificationResult(ok=not errors, checked=len(self.entries), errors=errors)
