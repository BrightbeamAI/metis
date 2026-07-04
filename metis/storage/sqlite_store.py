"""Local SQLite persistence for fragments, memory objects, artefacts, and evidence.

This is a convenience backend for ``metis init`` and the CLI. The CHAP evidence chain
remains the source of truth for audit; this store mirrors live state for querying.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from ..fragment.model import TacitFragment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fragments (id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_objects (id TEXT PRIMARY KEY, fragment_id TEXT, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artefacts (id TEXT PRIMARY KEY, kind TEXT, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence (seq INTEGER PRIMARY KEY, json TEXT NOT NULL);
"""


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # FragmentBackend protocol
    def save_fragment(self, fragment: TacitFragment) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO fragments (id, json) VALUES (?, ?)",
            (fragment.fragment_id, fragment.model_dump_json()))
        self.conn.commit()

    def load_fragments(self) -> Iterable[TacitFragment]:
        rows = self.conn.execute("SELECT json FROM fragments").fetchall()
        return [TacitFragment.model_validate_json(r[0]) for r in rows]

    def save_memory_object(self, memory_id: str, fragment_id: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO memory_objects (id, fragment_id, json) VALUES (?, ?, ?)",
            (memory_id, fragment_id, json.dumps(payload)))
        self.conn.commit()

    def save_artefact(self, artefact: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO artefacts (id, kind, json) VALUES (?, ?, ?)",
            (artefact["id"], artefact.get("kind"), json.dumps(artefact)))
        self.conn.commit()

    def save_evidence(self, record: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO evidence (seq, json) VALUES (?, ?)",
            (record["seq"], json.dumps(record)))
        self.conn.commit()

    def persist_engine(self, engine) -> None:
        for frag in engine.fragments.all():
            self.save_fragment(frag)
        for mo in engine.tacit_store.all():
            self.save_memory_object(mo.memory_id, mo.fragment_id, mo.model_dump(mode="json"))
        for art in engine.adapter.artefacts.values():
            self.save_artefact(art)
        for rec in engine.adapter.evidence_records():
            self.save_evidence(rec)

    def close(self) -> None:
        self.conn.close()
