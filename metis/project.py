"""A local Metis project: persistent CHAP coordinator, per-workspace domain state, and an
append-only evidence ledger for every workspace.

Layout (``$METIS_HOME``, default ``./.metis``)::

    chap.db                          the CHAP coordinator's SQLite store (all workspaces)
    project.json                     the active workspace
    workspaces/<id>/state.json       Metis domain state: fragments, memory, stores, counters
    workspaces/<id>/evidence.jsonl   append-only ledger, one line per CHAP evidence entry
    workspaces/<id>/metis.db         queryable SQLite copy of the domain state

Every open restores the coordinator from ``chap.db``, so a workspace's hash-linked chain
continues across commands instead of starting again. Running another scenario never
overwrites a workspace: each run gets its own.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .audit.ledger import EvidenceLedger
from .engine import MetisEngine
from .models.model_config import project_home


class NoWorkspace(FileNotFoundError):
    """The project has no workspace to open yet."""


class Project:
    def __init__(self, home: str | Path | None = None) -> None:
        self.home = Path(home) if home else project_home()

    # ---- paths -------------------------------------------------------------------
    @property
    def chap_db(self) -> Path:
        return self.home / "chap.db"

    @property
    def _project_file(self) -> Path:
        return self.home / "project.json"

    def workspace_dir(self, workspace_id: str) -> Path:
        return self.home / "workspaces" / workspace_id

    def state_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "state.json"

    def ledger_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "evidence.jsonl"

    # ---- workspaces ----------------------------------------------------------------
    def init(self) -> None:
        (self.home / "workspaces").mkdir(parents=True, exist_ok=True)
        self.chap_store().close()

    def workspace_ids(self) -> list[str]:
        root = self.home / "workspaces"
        if not root.exists():
            return []
        return sorted(p.name for p in root.iterdir() if (p / "state.json").exists())

    def active_workspace(self) -> str | None:
        if not self._project_file.exists():
            return None
        return json.loads(self._project_file.read_text()).get("active_workspace")

    def set_active(self, workspace_id: str) -> None:
        if workspace_id not in self.workspace_ids():
            raise NoWorkspace(f"No workspace {workspace_id!r} in {self.home}.")
        self.home.mkdir(parents=True, exist_ok=True)
        self._project_file.write_text(json.dumps({"active_workspace": workspace_id}, indent=2))

    def unique_workspace_id(self, base: str) -> str:
        """``base`` if unused in this project, else ``base-2``, ``base-3``, ..."""
        taken = set(self.workspace_ids()) | self._stored_workspace_ids()
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    def _stored_workspace_ids(self) -> set[str]:
        if not self.chap_db.exists():
            return set()
        store = self.chap_store()
        try:
            return {record.id for record in store.load()}
        finally:
            store.close()

    # ---- engines -------------------------------------------------------------------
    def chap_store(self) -> Any:
        from chap_coordinator.storage.sqlite import SqliteStore

        self.home.mkdir(parents=True, exist_ok=True)
        return SqliteStore(str(self.chap_db))

    def create_engine(self, workspace_id: str, *, name: str, site: str = "plant_a",
                      use_live_model: bool = False) -> MetisEngine:
        """A live engine for a new workspace, persisted in this project."""
        return MetisEngine(workspace_id=workspace_id, name=name, deterministic=False, site=site,
                           use_live_model=use_live_model, chap_store=self.chap_store(),
                           ledger=EvidenceLedger(self.ledger_path(workspace_id)))

    def load_state(self, workspace_id: str | None = None) -> dict[str, Any]:
        workspace_id = workspace_id or self.active_workspace()
        if not workspace_id or not self.state_path(workspace_id).exists():
            raise NoWorkspace(f"No Metis workspace in {self.home}. "
                              "Run `metis demo manufacturing-pump-vibration` first.")
        return json.loads(self.state_path(workspace_id).read_text())

    def open(self, workspace_id: str | None = None, *, use_live_model: bool = False) -> MetisEngine:
        """Reopen a workspace: its CHAP chain continues where it stopped."""
        workspace_id = workspace_id or self.active_workspace()
        state = self.load_state(workspace_id)
        engine = MetisEngine(workspace_id=workspace_id, name=state.get("name", workspace_id),
                             deterministic=False, site=state.get("site", "plant_a"),
                             use_live_model=use_live_model, chap_store=self.chap_store(),
                             ledger=EvidenceLedger(self.ledger_path(workspace_id)))
        engine.import_state(state)
        return engine

    def save(self, engine: MetisEngine) -> Path:
        """Write the workspace's domain state and make it the active workspace."""
        workspace_id = engine.adapter.workspace_id
        target = self.state_path(workspace_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(engine.export_state(), indent=2))
        self.set_active(workspace_id)
        try:
            from .storage.sqlite_store import SqliteStore

            mirror = SqliteStore(self.workspace_dir(workspace_id) / "metis.db")
            mirror.persist_engine(engine)
            mirror.close()
        except Exception as exc:
            # state.json and the CHAP store are authoritative; the SQLite copy is for
            # querying. Its failure must be visible, never silent.
            print(f"warning: state saved, but the SQLite copy failed: {exc}", file=sys.stderr)
        return target
