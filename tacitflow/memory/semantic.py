"""Semantic memory, organisational concepts, facts, equipment/product metadata."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..conditions.context import TacitContext
from .agent_context import MemoryEntry


def _matches_context(metadata: dict[str, Any], context: TacitContext | None) -> bool:
    if context is None:
        return True
    for key in ("equipment_id", "equipment_family", "product_family", "line", "area", "site"):
        want = getattr(context, key, None)
        have = metadata.get(key)
        if want is not None and have is not None:
            want_set = set(want) if isinstance(want, list) else {want}
            have_set = set(have) if isinstance(have, list) else {have}
            if not (want_set & have_set):
                return False
    return True


class SemanticMemoryStore:
    def __init__(self) -> None:
        self.entries: list[MemoryEntry] = []

    def add(self, source: str, content: Any, **metadata: Any) -> None:
        self.entries.append(MemoryEntry(source=source, content=content, metadata=dict(metadata)))

    def load_dir(self, path: str | Path) -> SemanticMemoryStore:
        p = Path(path)
        if p.exists():
            for f in sorted(p.glob("*.json")):
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    for item in data:
                        meta = item if isinstance(item, dict) else {}
                        self.add(f.stem, item, **{k: meta[k] for k in meta if k in
                                 ("equipment_id", "equipment_family", "product_family", "line", "area", "site")})
                else:
                    meta = data if isinstance(data, dict) else {}
                    self.add(f.stem, data, **{k: meta[k] for k in meta if k in
                             ("equipment_id", "equipment_family", "product_family", "line", "area", "site")})
        return self

    def query(self, context: TacitContext | None = None, limit: int | None = None) -> list[MemoryEntry]:
        out = [e for e in self.entries if _matches_context(e.metadata, context)]
        return out[:limit] if limit else out
