"""Export the CHAP-compatible evidence chain as portable JSONL.

Each line is one evidence entry plus the full signed envelope, so the export is both an
audit log and a replayable record. The chain is append-only and never mutated.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _entries(source: Any):
    chain = getattr(source, "chain", source)
    return chain.entries


def export_records(source: Any) -> list[dict[str, Any]]:
    records = []
    for entry in _entries(source):
        rec = entry.to_record()
        rec["envelope"] = entry.envelope
        records.append(rec)
    return records


def export_jsonl(source: Any, path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = export_records(source)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return len(records)
