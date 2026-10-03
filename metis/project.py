"""A local Metis project: persistent CHAP coordinator, per-workspace domain state in SQLite,
and an append-only evidence ledger for every workspace.

Layout (``$METIS_HOME``, default ``./.metis``)::

    chap.db                          the CHAP coordinator's SQLite store (all workspaces)
    project.json                     the active workspace
    workspaces/<id>/metis.db         Metis domain state in SQLite: fragments, memory, stores,
                                     pending captures, counters (the authoritative copy)
    workspaces/<id>/evidence.jsonl   append-only ledger, one line per CHAP evidence entry
    workspaces/<id>/.lock            held by the one process writing the workspace

Every open restores the coordinator from ``chap.db``, so a workspace's hash-linked chain
continues across commands instead of starting again. Running another scenario never
overwrites a workspace: each run gets its own. A workspace has one writer at a time;
read-only opens (inspection and verification) work while a writer is running.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .audit.ledger import EvidenceLedger
from .engine import MetisEngine
from .models.model_config import project_home
from .storage import lock
from .storage.lock import WorkspaceBusy
from .storage.sqlite_store import SqliteStore

__all__ = ["NoWorkspace", "Project", "WorkspaceBusy"]


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

    def state_db(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "metis.db"

    def ledger_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "evidence.jsonl"

    def _lock_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / ".lock"

    # ---- workspaces ----------------------------------------------------------------
    def init(self) -> None:
        (self.home / "workspaces").mkdir(parents=True, exist_ok=True)
        self.chap_store().close()

    def workspace_ids(self) -> list[str]:
        root = self.home / "workspaces"
        if not root.exists():
            return []
        return sorted(p.name for p in root.iterdir() if (p / "metis.db").exists())

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
        from chap_coordinator.storage.sqlite import SqliteStore as ChapStore

        self.home.mkdir(parents=True, exist_ok=True)
        return ChapStore(str(self.chap_db))

    def create_engine(self, workspace_id: str, *, name: str, site: str = "plant_a",
                      use_live_model: bool = False) -> MetisEngine:
        """A live engine for a new workspace, persisted in this project."""
        lock.acquire(self._lock_path(workspace_id))
        return MetisEngine(workspace_id=workspace_id, name=name, deterministic=False, site=site,
                           use_live_model=use_live_model, chap_store=self.chap_store(),
                           ledger=EvidenceLedger(self.ledger_path(workspace_id)))

    def load_state(self, workspace_id: str | None = None) -> dict[str, Any]:
        workspace_id = workspace_id or self.active_workspace()
        state = None
        if workspace_id and self.state_db(workspace_id).exists():
            store = SqliteStore(self.state_db(workspace_id))
            try:
                state = store.load_state()
            finally:
                store.close()
        if state is None:
            raise NoWorkspace(f"No Metis workspace in {self.home}. "
                              "Run `metis demo manufacturing-pump-vibration` first.")
        return state

    def open(self, workspace_id: str | None = None, *, use_live_model: bool = False,
             read_only: bool = False) -> MetisEngine:
        """Reopen a workspace: its CHAP chain continues where it stopped.

        A writer holds the workspace lock for the life of the process. ``read_only`` opens
        take no lock and refuse to record anything, so inspection and verification work
        alongside a running writer such as ``metis mcp``.
        """
        workspace_id = workspace_id or self.active_workspace()
        state = self.load_state(workspace_id)
        if not read_only:
            lock.acquire(self._lock_path(workspace_id))
        engine = MetisEngine(workspace_id=workspace_id, name=state.get("name") or workspace_id,
                             deterministic=False, site=state.get("site") or "plant_a",
                             use_live_model=use_live_model, chap_store=self.chap_store(),
                             ledger=EvidenceLedger(self.ledger_path(workspace_id),
                                                   read_only=read_only))
        engine.import_state(state)
        return engine

    def close(self, workspace_id: str) -> None:
        """Stop writing ``workspace_id`` from this process, so another process may open it."""
        lock.release(self._lock_path(workspace_id))

    def save(self, engine: MetisEngine) -> Path:
        """Write the workspace's domain state in one transaction; make it active."""
        workspace_id = engine.adapter.workspace_id
        if not lock.held(self._lock_path(workspace_id)):
            raise WorkspaceBusy(f"{workspace_id} was not opened for writing by this process.")
        target = self.state_db(workspace_id)
        store = SqliteStore(target)
        try:
            store.save_state(engine.export_state())
        finally:
            store.close()
        self.set_active(workspace_id)
        return target
