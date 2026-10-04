"""A SQL workspace repository for PostgreSQL (production) and SQLite (a single server).

Tables
------
``metis_workspaces``       one row per workspace: name, site, a version counter, and the Metis
                           domain state as JSON (fragments, memory, members, references).
``chap_workspaces``        the CHAP coordinator's snapshot of each workspace, in CHAP's own
                           store schema, so CHAP tooling can read it.
``metis_evidence_ledger``  one row per CHAP evidence entry, appended as it is recorded. Database
                           triggers refuse updates and deletes, so recorded history stays as it is.
``metis_schema``           the schema version.

One writer per workspace
------------------------
A CHAP coordinator is a single writer, so every write to a workspace is serialised: within one
process by a lock, across processes by a PostgreSQL advisory lock held for the transaction, and
in every case by a version check when the domain state is saved. A write commits the domain
state, the CHAP snapshot, and the new ledger entries in one transaction, or rolls all of them
back. Engines are cached between requests and rebuilt from the database when another process
has written the workspace since, or when an operation failed part-way.

With SQLite, run one server process: SQLite allows one writer for the whole database, so this
repository serialises all writes in the process.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool

from ..audit.ledger import LedgerMismatch
from ..engine import MetisEngine
from .repository import (
    StorageCorruption,
    UnknownWorkspace,
    WorkspaceConflict,
    WorkspaceExists,
    WorkspaceSettings,
    WorkspaceSummary,
)

T = TypeVar("T")

SCHEMA_VERSION = 1

metadata = MetaData()
schema_table = Table("metis_schema", metadata, Column("version", Integer, nullable=False))
workspaces_table = Table(
    "metis_workspaces", metadata,
    Column("id", String(80), primary_key=True),
    Column("name", Text, nullable=False),
    Column("site", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("state", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
chap_table = Table(
    "chap_workspaces", metadata,
    Column("id", Text, primary_key=True),
    Column("data", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("updated_at", Text, nullable=False),
)
ledger_table = Table(
    "metis_evidence_ledger", metadata,
    Column("workspace_id", String(80), primary_key=True),
    Column("seq", Integer, primary_key=True, autoincrement=False),
    Column("record", Text, nullable=False),
    Column("recorded_at", String(40), nullable=False),
)

_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS metis_ledger_no_update BEFORE UPDATE ON metis_evidence_ledger "
    "BEGIN SELECT RAISE(ABORT, 'metis_evidence_ledger is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS metis_ledger_no_delete BEFORE DELETE ON metis_evidence_ledger "
    "BEGIN SELECT RAISE(ABORT, 'metis_evidence_ledger is append-only'); END",
)
_POSTGRES_TRIGGERS = (
    "CREATE OR REPLACE FUNCTION metis_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN RAISE EXCEPTION 'metis_evidence_ledger is append-only'; END; $$",
    "DROP TRIGGER IF EXISTS metis_ledger_append_only ON metis_evidence_ledger",
    "CREATE TRIGGER metis_ledger_append_only BEFORE UPDATE OR DELETE ON metis_evidence_ledger "
    "FOR EACH ROW EXECUTE FUNCTION metis_ledger_append_only()",
    "DROP TRIGGER IF EXISTS metis_ledger_no_truncate ON metis_evidence_ledger",
    "CREATE TRIGGER metis_ledger_no_truncate BEFORE TRUNCATE ON metis_evidence_ledger "
    "FOR EACH STATEMENT EXECUTE FUNCTION metis_ledger_append_only()",
)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def normalise_url(url: str) -> str:
    """Use the psycopg 3 driver for PostgreSQL URLs that name no driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _create_db(url: str, echo: bool = False) -> Engine:
    url = normalise_url(url)
    if url.startswith("sqlite"):
        memory = url in ("sqlite://", "sqlite:///:memory:")
        if not memory and url.startswith("sqlite:///"):
            Path(url[len("sqlite:///"):]).expanduser().parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if memory:
            kwargs["poolclass"] = StaticPool
        db = create_engine(url, echo=echo, **kwargs)

        @event.listens_for(db, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout = 10000")
            if not memory:
                cursor.execute("PRAGMA journal_mode = WAL")
            cursor.close()

        return db
    return create_engine(url, echo=echo, pool_pre_ping=True)


def _advisory_key(workspace_id: str) -> int:
    digest = hashlib.sha256(f"metis:{workspace_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


_FIELDS: dict[type, tuple[str, ...]] = {}


def _dataclass_json(value: Any) -> dict[str, Any]:
    """``json.dumps`` support for CHAP's dataclasses: the same fields ``dataclasses.asdict``
    writes, so the JSON equals CHAP's own snapshot, produced in one pass."""
    cls = type(value)
    names = _FIELDS.get(cls)
    if names is None:
        if not dataclasses.is_dataclass(value):
            raise TypeError(f"{cls.__name__} is not JSON serialisable")
        names = _FIELDS[cls] = tuple(f.name for f in dataclasses.fields(value))
    return {name: getattr(value, name) for name in names}


def workspace_snapshot_json(coord: Any, workspace_id: str) -> tuple[str, int] | None:
    """A workspace's CHAP snapshot as JSON, and its version (the number of audit entries)."""
    ws = coord.workspaces.get(workspace_id)
    if ws is None:
        return None
    return json.dumps(ws, default=_dataclass_json, sort_keys=True), len(ws.audit)


# ---- the CHAP store and the ledger, bound to the current transaction ------------------------
class SqlChapStore:
    """CHAP's ``Store`` protocol over the repository's database, for one workspace.

    The repository gives this store to the coordinator only to restore the workspace. It then
    takes one snapshot per transaction (``capture``) and writes it on commit, which spares the
    coordinator a full snapshot after every dispatch.
    """

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self.conn: Connection | None = None
        self.pending: Any = None
        self.pending_json: tuple[str, int] | None = None

    def bind(self, conn: Connection | None) -> None:
        self.conn = conn

    def _conn(self) -> Connection:
        if self.conn is None:
            raise RuntimeError("The CHAP store is used outside a repository transaction.")
        return self.conn

    def load(self) -> list[Any]:
        from chap_coordinator.storage.store import WorkspaceRecord

        row = self._conn().execute(
            select(chap_table).where(chap_table.c.id == self.workspace_id)).first()
        if row is None:
            return []
        return [WorkspaceRecord(id=row.id, data=json.loads(row.data), version=row.version,
                                updated_at=row.updated_at)]

    def save(self, record: Any) -> None:
        if record.id == self.workspace_id:
            self.pending = record

    def capture(self, coord: Any) -> None:
        """Take the workspace's snapshot from the coordinator, to write on ``flush``."""
        self.pending_json = workspace_snapshot_json(coord, self.workspace_id)

    def flush(self) -> None:
        if self.pending_json is not None:
            (data, version), self.pending_json = self.pending_json, None
            self.pending = None
            values = {"data": data, "version": version, "updated_at": _now()}
        elif self.pending is not None:
            record, self.pending = self.pending, None
            values = {"data": json.dumps(record.data, sort_keys=True), "version": record.version,
                      "updated_at": record.updated_at}
        else:
            return
        conn = self._conn()
        result = conn.execute(update(chap_table).where(chap_table.c.id == self.workspace_id)
                              .values(**values))
        if result.rowcount == 0:
            conn.execute(insert(chap_table).values(id=self.workspace_id, **values))

    def discard(self) -> None:
        self.pending = None
        self.pending_json = None

    def delete(self, id: str) -> None:  # noqa: A002 - the CHAP Store protocol's name
        raise PermissionError("Metis keeps every workspace's evidence; workspaces are not deleted.")

    def close(self) -> None:
        self.pending = None


class SqlLedger:
    """The append-only evidence ledger of one workspace, in ``metis_evidence_ledger``."""

    def __init__(self, workspace_id: str, *, read_only: bool = False) -> None:
        self.workspace_id = workspace_id
        self.read_only = read_only
        self.conn: Connection | None = None
        self._count: int | None = None

    def bind(self, conn: Connection | None) -> None:
        self.conn = conn
        self._count = None

    def _conn(self) -> Connection:
        if self.conn is None:
            raise RuntimeError("The ledger is used outside a repository transaction.")
        return self.conn

    @property
    def path(self) -> str:
        return f"metis_evidence_ledger[{self.workspace_id}]"

    @property
    def count(self) -> int:
        if self._count is None:
            self._count = self._conn().execute(
                select(func.count()).select_from(ledger_table)
                .where(ledger_table.c.workspace_id == self.workspace_id)).scalar_one()
        return self._count

    def records(self) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            select(ledger_table.c.record).where(ledger_table.c.workspace_id == self.workspace_id)
            .order_by(ledger_table.c.seq)).scalars()
        return [json.loads(r) for r in rows]

    def sync(self, adapter: Any) -> int:
        """Append every chain entry the ledger does not hold yet; return how many."""
        new = adapter.chain.entries[self.count:]
        if not new:
            return 0
        if self.read_only:
            raise PermissionError(f"{self.path} was opened read-only.")
        now = _now()
        self._conn().execute(insert(ledger_table), [
            {"workspace_id": self.workspace_id, "seq": entry.seq,
             "record": json.dumps(adapter.evidence_record(entry), separators=(",", ":")),
             "recorded_at": now} for entry in new])
        self._count = self.count + len(new)
        return len(new)

    def matches(self, adapter: Any) -> bool:
        stored = [json.loads(json.dumps(adapter.evidence_record(e), separators=(",", ":")))
                  for e in adapter.chain.entries]
        return self.records() == stored

    def check(self, adapter: Any) -> None:
        entries = adapter.chain.entries
        if self.count > len(entries):
            raise LedgerMismatch(f"{self.path} holds {self.count} entries but the CHAP store "
                                 f"holds {len(entries)}.")
        if self.count:
            last = json.loads(self._conn().execute(
                select(ledger_table.c.record).where(ledger_table.c.workspace_id == self.workspace_id)
                .order_by(ledger_table.c.seq.desc()).limit(1)).scalar_one())
            stored = entries[self.count - 1]
            if last.get("seq") != stored.seq or last.get("prev_hash") != getattr(stored, "prev_hash", None):
                raise LedgerMismatch(f"{self.path} disagrees with the CHAP store at seq {last.get('seq')}.")


# ---- the repository ------------------------------------------------------------------------
@dataclass
class _Cached:
    engine: MetisEngine
    version: int


class SqlRepository:
    """Workspaces in PostgreSQL or SQLite, with one writer per workspace.

    ``url`` is a SQLAlchemy URL: ``postgresql://user:pass@host/db`` (psycopg 3) or
    ``sqlite:///path/metis.db``. ``engine_options`` are passed to every ``MetisEngine`` built
    (for example ``use_live_model``).
    """

    def __init__(self, url: str, *, echo: bool = False, cache_size: int = 64,
                 engine_options: dict[str, Any] | None = None, migrate: bool = True) -> None:
        self.url = normalise_url(url)
        self.db = _create_db(self.url, echo=echo)
        self.dialect = self.db.dialect.name
        self.engine_options = dict(engine_options or {})
        self.cache_size = max(1, cache_size)
        self._cache: OrderedDict[str, _Cached] = OrderedDict()
        self._cache_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._sqlite_lock = threading.RLock()
        if migrate:
            self.migrate()

    # -- schema --
    def migrate(self) -> int:
        """Create or upgrade the schema; return its version. Safe to run from several
        processes at once: on PostgreSQL an advisory lock serialises them."""
        with self._global(), self.db.begin() as conn:
            if self.dialect == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                             {"key": _advisory_key("__schema__")})
            metadata.create_all(conn)
            for statement in (_POSTGRES_TRIGGERS if self.dialect == "postgresql"
                              else _SQLITE_TRIGGERS if self.dialect == "sqlite" else ()):
                conn.execute(text(statement))
            version = conn.execute(select(schema_table.c.version)).scalar()
            if version is None:
                conn.execute(insert(schema_table).values(version=SCHEMA_VERSION))
                version = SCHEMA_VERSION
            elif version > SCHEMA_VERSION:
                raise StorageCorruption(
                    f"The database schema is version {version}; this Metis knows up to "
                    f"{SCHEMA_VERSION}. Upgrade Metis.")
        return version

    def ping(self) -> bool:
        with self._global(), self.db.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True

    def _global(self) -> Any:
        """The SQLite writer lock, or no lock for PostgreSQL."""
        return self._sqlite_lock if self.dialect == "sqlite" else nullcontext()

    def close(self) -> None:
        with self._cache_guard:
            self._cache.clear()
        self.db.dispose()

    # -- locks and cache --
    def _lock_for(self, workspace_id: str) -> threading.RLock:
        if self.dialect == "sqlite":
            return self._sqlite_lock
        with self._locks_guard:
            return self._locks.setdefault(workspace_id, threading.RLock())

    def _db_lock(self, conn: Connection, workspace_id: str) -> None:
        if self.dialect == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                         {"key": _advisory_key(workspace_id)})

    def _cached(self, workspace_id: str, version: int) -> MetisEngine | None:
        with self._cache_guard:
            entry = self._cache.get(workspace_id)
            if entry is None or entry.version != version:
                return None
            self._cache.move_to_end(workspace_id)
            return entry.engine

    def _remember(self, workspace_id: str, engine: MetisEngine, version: int) -> None:
        with self._cache_guard:
            self._cache[workspace_id] = _Cached(engine, version)
            self._cache.move_to_end(workspace_id)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    def _forget(self, workspace_id: str) -> None:
        with self._cache_guard:
            self._cache.pop(workspace_id, None)

    # -- engines --
    @staticmethod
    def _bind(engine: MetisEngine, conn: Connection | None) -> None:
        engine.adapter.store.bind(conn)
        engine.adapter.ledger.bind(conn)

    def _new_engine(self, conn: Connection, workspace_id: str, *, name: str, site: str,
                    **settings: Any) -> MetisEngine:
        store, ledger = SqlChapStore(workspace_id), SqlLedger(workspace_id)
        store.bind(conn)
        ledger.bind(conn)
        options = {**self.engine_options, **settings}
        engine = MetisEngine(workspace_id=workspace_id, name=name, deterministic=False,
                             site=site, chap_store=store, ledger=ledger, members=[], **options)
        engine.adapter.detach_store()  # one snapshot per transaction, taken in _persist
        return engine

    @staticmethod
    def _persist(engine: MetisEngine) -> None:
        """Write the CHAP snapshot and any ledger entries not written yet."""
        store = engine.adapter.store
        store.capture(engine.adapter.coord)
        store.flush()
        engine.adapter.ledger.sync(engine.adapter)

    def _engine_for(self, conn: Connection, workspace_id: str, row: Any) -> MetisEngine:
        engine = self._cached(workspace_id, row.version)
        if engine is not None:
            self._bind(engine, conn)
            return engine
        chap_version = conn.execute(select(chap_table.c.version)
                                    .where(chap_table.c.id == workspace_id)).scalar()
        if chap_version is None:
            raise StorageCorruption(f"{workspace_id} has no CHAP chain in chap_workspaces.")
        state = json.loads(row.state)
        engine = self._new_engine(
            conn, workspace_id, name=row.name, site=row.site,
            escalation_assignee=state.get("escalation_assignee"),
            review_rule=state.get("review_rule"),
            **({"whisper_deadline_ms": state["whisper_deadline_ms"]}
               if state.get("whisper_deadline_ms") else {}))
        if engine.adapter.chain.count != chap_version:
            # The coordinator could not restore the stored chain and started another.
            raise StorageCorruption(f"{workspace_id}: the stored CHAP chain could not be restored.")
        engine.import_state(state)
        return engine

    def _save(self, conn: Connection, engine: MetisEngine, workspace_id: str, expected: int) -> int:
        self._persist(engine)
        state = json.dumps(engine.export_state(), sort_keys=True)
        result = conn.execute(
            update(workspaces_table)
            .where(workspaces_table.c.id == workspace_id, workspaces_table.c.version == expected)
            .values(version=expected + 1, state=state, name=engine.adapter.name,
                    updated_at=_now()))
        if result.rowcount != 1:
            raise WorkspaceConflict(f"{workspace_id} was changed by another writer.")
        return expected + 1

    # -- public operations --
    def create(self, settings: WorkspaceSettings, *, by: str) -> dict[str, Any]:
        """Create a workspace with its system participants and initial members."""
        workspace_id = settings.id
        with self._lock_for(workspace_id):
            try:
                with self.db.begin() as conn:
                    self._db_lock(conn, workspace_id)
                    exists = conn.execute(select(workspaces_table.c.id)
                                          .where(workspaces_table.c.id == workspace_id)).first()
                    taken = conn.execute(select(chap_table.c.id)
                                         .where(chap_table.c.id == workspace_id)).first()
                    if exists or taken:
                        raise WorkspaceExists(f"Workspace {workspace_id} already exists.")
                    engine = self._new_engine(
                        conn, workspace_id, name=settings.name, site=settings.site,
                        escalation_assignee=settings.escalation_assignee,
                        review_rule=settings.review_rule,
                        whisper_deadline_ms=settings.whisper_deadline_ms)
                    engine.join_system_participants()
                    for member in settings.members:
                        engine.set_member(member.uri, list(member.roles), by=by,
                                          display_name=member.display_name,
                                          reason="initial member")
                    self._persist(engine)
                    now = _now()
                    conn.execute(insert(workspaces_table).values(
                        id=workspace_id, name=settings.name, site=settings.site, version=1,
                        state=json.dumps(engine.export_state(), sort_keys=True),
                        created_at=now, updated_at=now))
                    descriptor = engine.adapter.descriptor()
                    self._bind(engine, None)
            except BaseException:
                self._forget(workspace_id)
                raise
            self._remember(workspace_id, engine, 1)
            return descriptor

    def list(self) -> list[WorkspaceSummary]:
        with self._global(), self.db.connect() as conn:
            rows = conn.execute(select(
                workspaces_table.c.id, workspaces_table.c.name, workspaces_table.c.site,
                workspaces_table.c.created_at, workspaces_table.c.updated_at,
                workspaces_table.c.version).order_by(workspaces_table.c.id)).all()
        return [WorkspaceSummary(id=r.id, name=r.name, site=r.site, created_at=r.created_at,
                                 updated_at=r.updated_at, version=r.version) for r in rows]

    def memberships(self, uri: str) -> dict[str, list[str]]:
        """The workspaces ``uri`` is a member of, with its roles in each, from committed state."""
        with self._global(), self.db.connect() as conn:
            rows = conn.execute(select(workspaces_table.c.id, workspaces_table.c.state)
                                .order_by(workspaces_table.c.id)).all()
        found: dict[str, list[str]] = {}
        for row in rows:
            for member in json.loads(row.state).get("members") or []:
                if member.get("uri") == uri and member.get("roles"):
                    found[row.id] = list(member["roles"])
        return found

    def exists(self, workspace_id: str) -> bool:
        with self._global(), self.db.connect() as conn:
            return conn.execute(select(workspaces_table.c.id)
                                .where(workspaces_table.c.id == workspace_id)).first() is not None

    def _row(self, conn: Connection, workspace_id: str) -> Any:
        row = conn.execute(select(
            workspaces_table.c.version, workspaces_table.c.state, workspaces_table.c.name,
            workspaces_table.c.site).where(workspaces_table.c.id == workspace_id)).first()
        if row is None:
            raise UnknownWorkspace(workspace_id)
        return row

    def write(self, workspace_id: str, fn: Callable[[MetisEngine], T], *, retries: int = 2) -> T:
        """Run ``fn`` as the workspace's one writer and commit what it records, or nothing."""
        for attempt in range(retries + 1):
            try:
                return self._write_once(workspace_id, fn)
            except WorkspaceConflict:
                if attempt == retries:
                    raise
        raise AssertionError("unreachable")

    def _write_once(self, workspace_id: str, fn: Callable[[MetisEngine], T]) -> T:
        with self._lock_for(workspace_id):
            try:
                with self.db.begin() as conn:
                    self._db_lock(conn, workspace_id)
                    row = self._row(conn, workspace_id)
                    engine = self._engine_for(conn, workspace_id, row)
                    try:
                        result = fn(engine)
                        version = self._save(conn, engine, workspace_id, row.version)
                    finally:
                        engine.adapter.store.discard()
                        self._bind(engine, None)
            except BaseException:
                self._forget(workspace_id)
                raise
            self._remember(workspace_id, engine, version)
            return result

    def read(self, workspace_id: str, fn: Callable[[MetisEngine], T]) -> T:
        """Run ``fn`` against the committed state of the workspace; it must record nothing."""
        with self._lock_for(workspace_id):
            try:
                with self.db.connect() as conn:  # closes with a rollback: a read writes nothing
                    row = self._row(conn, workspace_id)
                    engine = self._engine_for(conn, workspace_id, row)
                    before = engine.adapter.chain.count
                    try:
                        result = fn(engine)
                    finally:
                        self._bind(engine, None)
                    if engine.adapter.chain.count != before:
                        raise RuntimeError("A read recorded evidence; use write for this operation.")
            except BaseException:
                self._forget(workspace_id)
                raise
            self._remember(workspace_id, engine, row.version)
            return result
