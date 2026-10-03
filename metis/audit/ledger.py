"""The append-only evidence ledger of one workspace.

Each CHAP evidence entry is written as one JSON line as soon as it is recorded, flushed to
disk, and never rewritten. The ledger is the human-inspectable record of a workspace and a
second copy of the chain that the CHAP SQLite store holds. On open the two are checked
against each other, so a lost write is detected instead of tolerated. Lines use the same
format as ``metis.audit.export``, so ``metis.audit.replay`` verifies a ledger directly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class LedgerMismatch(RuntimeError):
    """The ledger and the CHAP store disagree about a workspace's chain."""


class EvidenceLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._count = self._read_count()

    def _read_count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open(encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())

    @property
    def count(self) -> int:
        return self._count

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def sync(self, adapter: Any) -> int:
        """Append every chain entry the ledger does not hold yet; return how many."""
        entries = adapter.chain.entries
        new = entries[self._count:]
        if not new:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            for entry in new:
                fh.write(json.dumps(adapter.evidence_record(entry), separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._count += len(new)
        return len(new)

    def check(self, adapter: Any) -> None:
        """Raise ``LedgerMismatch`` if the ledger and the restored chain disagree."""
        entries = adapter.chain.entries
        if self._count > len(entries):
            raise LedgerMismatch(
                f"{self.path} holds {self._count} entries but the CHAP store holds "
                f"{len(entries)}: the coordinator state was not fully persisted.")
        if self._count:
            last = self.records()[self._count - 1]
            stored = entries[self._count - 1]
            if last.get("seq") != stored.seq or last.get("prev_hash") != getattr(stored, "prev_hash", None):
                raise LedgerMismatch(
                    f"{self.path} disagrees with the CHAP store at seq {last.get('seq')}.")
