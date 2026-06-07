"""Replay and verify an exported evidence chain (independent of the live adapter)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..integrations.chap.canonical import ZERO_HASH, sha256_hex
from ..integrations.chap.crypto import derive_private_key, verify
from ..integrations.chap.envelope import canonical_without_sig


@dataclass
class ReplayResult:
    ok: bool
    checked: int
    errors: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def replay(path: str | Path) -> ReplayResult:
    records = load_jsonl(path)
    errors: list[str] = []
    methods: list[str] = []
    expected_prev = ZERO_HASH
    for rec in records:
        env = rec["envelope"]
        canonical = canonical_without_sig(env)
        if sha256_hex(canonical) != rec["envelope_hash"]:
            errors.append(f"seq {rec['seq']}: envelope_hash mismatch")
        if rec["prev_hash"] != expected_prev:
            errors.append(f"seq {rec['seq']}: prev_hash break")
        pub = derive_private_key(rec["from"]).public_key()
        if not verify(canonical, rec["sig"], pub):
            errors.append(f"seq {rec['seq']}: signature invalid")
        methods.append(rec.get("method_or_type", "?"))
        expected_prev = sha256_hex(canonical + rec["sig"].encode("utf-8"))
    return ReplayResult(ok=not errors, checked=len(records), errors=errors, methods=methods)
