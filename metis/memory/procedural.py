"""Procedural memory, formal procedures, SOPs, workflows, checklists, policies."""
from __future__ import annotations

from pathlib import Path

from ..conditions.context import TacitContext
from .agent_context import MemoryEntry


class ProceduralMemoryStore:
    def __init__(self) -> None:
        self.entries: list[MemoryEntry] = []

    def add(self, source: str, content: str, **metadata: object) -> None:
        self.entries.append(MemoryEntry(source=source, content=content, metadata=dict(metadata)))

    def load_dir(self, path: str | Path) -> ProceduralMemoryStore:
        p = Path(path)
        if p.exists():
            for f in sorted(p.glob("*.md")):
                self.add(f.stem, f.read_text())
            for f in sorted(p.glob("*.txt")):
                self.add(f.stem, f.read_text())
        return self

    def query(self, context: TacitContext | None = None, limit: int | None = None) -> list[MemoryEntry]:
        # Formal procedures are generally applicable; return all (optionally capped).
        return self.entries[:limit] if limit else list(self.entries)
