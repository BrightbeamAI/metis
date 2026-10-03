"""SQLite persistence for a workspace's Metis domain state.

This is the authoritative store for tacit fragments, memory objects, the procedural,
semantic, and episodic memory entries, pending captures, and the workspace's counters and
CHAP references. Every save is one transaction, so a crash leaves either the previous state
or the new one, never a partial write. Fragment and memory rows carry their category, layer,
and state as columns, so the store can be queried directly with SQL. The CHAP evidence chain
itself lives in the CHAP store (``chap.db``) and the append-only ledger.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..fragment.model import TacitFragment

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fragments (
    id TEXT PRIMARY KEY, category TEXT, authority_layer TEXT, validation_state TEXT,
    revocation_status TEXT, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_objects (
    id TEXT PRIMARY KEY, fragment_id TEXT, authority_layer TEXT, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_entries (
    store TEXT NOT NULL, position INTEGER NOT NULL, json TEXT NOT NULL,
    PRIMARY KEY (store, position));
CREATE TABLE IF NOT EXISTS pending_captures (
    whisper_id TEXT PRIMARY KEY, worker TEXT, json TEXT NOT NULL);
"""

_META_KEYS = ("version", "name", "site", "workspace", "counters", "governance_refs")
_STORES = ("procedural", "semantic", "episodic")


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        with self.conn:
            self.conn.executescript(_SCHEMA)
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                              (json.dumps(SCHEMA_VERSION),))

    def save_state(self, state: dict[str, Any]) -> None:
        """Replace the stored domain state with ``state`` in one transaction."""
        with self.conn:
            for table in ("fragments", "memory_objects", "memory_entries", "pending_captures"):
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.executemany(
                "INSERT INTO fragments VALUES (?, ?, ?, ?, ?, ?)",
                [(f["fragment_id"], f["category"], f["authority_layer"], f["validation_state"],
                  f["revocation_status"], json.dumps(f)) for f in state.get("fragments", [])])
            self.conn.executemany(
                "INSERT INTO memory_objects VALUES (?, ?, ?, ?)",
                [(m["memory_id"], m["fragment_id"], m["authority_layer"], json.dumps(m))
                 for m in state.get("memory_objects", [])])
            self.conn.executemany(
                "INSERT INTO memory_entries VALUES (?, ?, ?)",
                [(store, i, json.dumps(e)) for store in _STORES
                 for i, e in enumerate(state.get(store, []))])
            self.conn.executemany(
                "INSERT INTO pending_captures VALUES (?, ?, ?)",
                [(p["whisper_id"], p["worker"], json.dumps(p)) for p in state.get("pending_captures", [])])
            self.conn.executemany(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                [(k, json.dumps(state.get(k))) for k in _META_KEYS])

    def load_state(self) -> dict[str, Any] | None:
        """The stored domain state, or ``None`` if nothing has been saved yet."""
        meta = {k: json.loads(v) for k, v in self.conn.execute("SELECT key, value FROM meta")}
        if "name" not in meta:
            return None
        state: dict[str, Any] = {k: meta.get(k) for k in _META_KEYS}
        state["fragments"] = [json.loads(r[0]) for r in
                              self.conn.execute("SELECT json FROM fragments ORDER BY id")]
        state["memory_objects"] = [json.loads(r[0]) for r in
                                   self.conn.execute("SELECT json FROM memory_objects ORDER BY id")]
        for store in _STORES:
            state[store] = [json.loads(r[0]) for r in self.conn.execute(
                "SELECT json FROM memory_entries WHERE store = ? ORDER BY position", (store,))]
        state["pending_captures"] = [json.loads(r[0]) for r in
                                     self.conn.execute("SELECT json FROM pending_captures")]
        return state

    def persist_engine(self, engine: Any) -> None:
        self.save_state(engine.export_state())

    def load_fragments(self) -> list[TacitFragment]:
        rows = self.conn.execute("SELECT json FROM fragments ORDER BY id").fetchall()
        return [TacitFragment.model_validate_json(r[0]) for r in rows]

    def close(self) -> None:
        self.conn.close()
