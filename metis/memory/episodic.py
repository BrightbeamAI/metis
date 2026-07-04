"""Episodic memory, specific past events, incidents, prior cases, CHAP evidence events."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..conditions.context import TacitContext
from .agent_context import MemoryEntry
from .semantic import _matches_context


class EpisodicMemoryStore:
    def __init__(self) -> None:
        self.entries: list[MemoryEntry] = []

    def add(self, source: str, content: Any, **metadata: Any) -> None:
        self.entries.append(MemoryEntry(source=source, content=content, metadata=dict(metadata)))

    def load_jsonl(self, path: str | Path) -> EpisodicMemoryStore:
        p = Path(path)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                source = case.get("id") or case.get("case_id") or "case"
                content = case.get("summary") or case
                self.add(source, content, **case)
        return self

    def query(self, context: TacitContext | None = None, limit: int | None = None) -> list[MemoryEntry]:
        out = [e for e in self.entries if _matches_context(e.metadata, context)]
        return out[:limit] if limit else out
