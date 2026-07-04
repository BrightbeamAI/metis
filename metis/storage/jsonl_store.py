"""Append-only JSONL store for portable records."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class JsonlStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, obj: dict[str, Any]) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(obj, separators=(",", ":")) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.read_all())
