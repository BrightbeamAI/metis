"""Replay and verify an exported evidence chain, independent of the live Coordinator.

Reproduces the Coordinator's hash linkage (``prev = sha256( JCS(envelope) || prev )``) over
the exported JSON-RPC envelopes and confirms prev_hash continuity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chap_coordinator import ZERO_HASH, canonicalize, sha256_hex


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
    prev = ZERO_HASH
    for rec in records:
        env = rec.get("envelope") or {}
        ph = rec.get("prev_hash")
        if ph is not None and ph != prev:
            errors.append(f"seq {rec.get('seq')}: prev_hash break")
        methods.append(rec.get("method_or_type") or env.get("method", "?"))
        prev = sha256_hex(canonicalize(env) + prev.encode("utf-8"))
    return ReplayResult(ok=not errors, checked=len(records), errors=errors, methods=methods)
