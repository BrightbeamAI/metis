"""Export the CHAP evidence chain as portable JSONL.

Each line is one audit entry (the dispatched JSON-RPC envelope plus its chain link), so the
export is both an audit log and a replayable record. The chain is append-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_records(source: Any) -> list[dict[str, Any]]:
    """Return the evidence records from an adapter (or anything with evidence_records())."""
    if hasattr(source, "evidence_records"):
        return source.evidence_records()
    adapter = getattr(source, "adapter", source)
    return adapter.evidence_records()


def export_jsonl(source: Any, path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = export_records(source)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return len(records)
