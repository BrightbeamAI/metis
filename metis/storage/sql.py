"""A SQL workspace repository for PostgreSQL (production) and SQLite (a single server).

Tables
------
``metis_workspaces``       one row per workspace: name, site, a version counter, a token unique
                           to each commit, and the Metis domain state as JSON (fragments,
                           memory, members, references).
``chap_workspaces``        the CHAP coordinator's snapshot of each workspace, in CHAP's own
                           store schema, so CHAP tooling can read it.
``metis_evidence_ledger``  one row per CHAP evidence entry, appended as it is recorded. Database
                           triggers refuse updates and deletes, so recorded history stays as it is.
``metis_members``          who belongs, or once belonged, to each workspace, with their roles;
                           an index of the members kept in the domain state.
``metis_outbox``           notifications awaiting delivery, written in the same transaction as
                           the evidence they report (see ``metis.notify``).
``metis_chat_identities``  where each person can be reached in a chat tool (Teams).
``metis_schema``           the schema version, and the oldest Metis schema that can use it.

One writer per workspace
------------------------
A CHAP coordinator is a single writer, so every write to a workspace is serialised: within one
process by a lock, across processes by a PostgreSQL advisory lock held for the transaction, and
in every case by a version check when the domain state is saved. A write commits the domain
state, the CHAP snapshot, the new ledger entries, and its notifications in one transaction, or
rolls all of them back. Engines are cached between requests and rebuilt from the database when
the stored commit token differs from the cached one (another process wrote the workspace, or the
database was restored), or when an operation failed part-way. Locks are waited for at most
``lock_timeout`` seconds; a workspace that stays busy longer raises ``WorkspaceBusy``.

Reads see one consistent snapshot: ``REPEATABLE READ`` on PostgreSQL, a read transaction on
SQLite. With SQLite, run one server process: SQLite allows one writer for the whole database,
so this repository serialises all writes in the process.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import re
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import (
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import StaticPool

from ..audit.ledger import LedgerMismatch
from ..engine import MetisEngine, StateTooNew
from .repository import (
    SchemaTooNew,
    StorageCorruption,
    UnknownWorkspace,
    WorkspaceBusy,
    WorkspaceConflict,
    WorkspaceExists,
    WorkspaceSettings,
    WorkspaceSummary,
)

T = TypeVar("T")

SCHEMA_VERSION = 4
# The oldest schema version whose code can use a database at SCHEMA_VERSION. A release that
# only adds tables or nullable columns keeps it; one that older code would misuse raises it.
MIN_COMPATIBLE = 4

metadata = MetaData()
schema_table = Table("metis_schema", metadata,
                     Column("version", Integer, nullable=False),
                     Column("min_compatible", Integer, nullable=True))
workspaces_table = Table(
    "metis_workspaces", metadata,
    Column("id", String(80), primary_key=True),
    Column("name", Text, nullable=False),
    Column("site", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("write_id", String(32), nullable=True),
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
members_table = Table(
    "metis_members", metadata,
    Column("workspace_id", String(80), primary_key=True),
    Column("participant", String(320), primary_key=True),
    Column("roles", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)
Index("ix_metis_members_participant", members_table.c.participant)

outbox_table = Table(
    "metis_outbox", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("workspace_id", String(80), nullable=False),
    Column("event", String(40), nullable=False),
    Column("channel", String(80), nullable=False),
    Column("recipient", Text, nullable=True),
    Column("payload", Text, nullable=False),
    Column("dedupe_key", String(400), nullable=True, unique=True),
    Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("next_attempt_at", String(32), nullable=False),
    Column("lease_token", String(32), nullable=True),
    Column("created_at", String(32), nullable=False),
    Column("delivered_at", String(32), nullable=True),
    Column("last_error", Text, nullable=True),
)
Index("ix_metis_outbox_due", outbox_table.c.status, outbox_table.c.next_attempt_at)
chat_identities_table = Table(
    "metis_chat_identities", metadata,
    Column("platform", String(20), primary_key=True),
    Column("participant", String(320), primary_key=True),
    Column("external_id", String(320), nullable=False),
    Column("reference", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)
Index("ix_metis_chat_identities_external", chat_identities_table.c.platform,
      chat_identities_table.c.external_id)

# Columns later schema versions added to tables that existed before them.
_ADDED_COLUMNS = (
    ("metis_schema", "min_compatible", "INTEGER"),
    ("metis_workspaces", "write_id", "VARCHAR(32)"),
    ("metis_outbox", "lease_token", "VARCHAR(32)"),
)

_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS metis_ledger_no_update BEFORE UPDATE ON metis_evidence_ledger "
    "BEGIN SELECT RAISE(ABORT, 'metis_evidence_ledger is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS metis_ledger_no_delete BEFORE DELETE ON metis_evidence_ledger "
    "BEGIN SELECT RAISE(ABORT, 'metis_evidence_ledger is append-only'); END",
)
_POSTGRES_FUNCTION = (
    "CREATE OR REPLACE FUNCTION metis_ledger_append_only() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN RAISE EXCEPTION 'metis_evidence_ledger is append-only'; END; $$")
_POSTGRES_TRIGGERS = {
    "metis_ledger_append_only":
        "CREATE TRIGGER metis_ledger_append_only BEFORE UPDATE OR DELETE ON metis_evidence_ledger "
        "FOR EACH ROW EXECUTE FUNCTION metis_ledger_append_only()",
    "metis_ledger_no_truncate":
        "CREATE TRIGGER metis_ledger_no_truncate BEFORE TRUNCATE ON metis_evidence_ledger "
        "FOR EACH STATEMENT EXECUTE FUNCTION metis_ledger_append_only()",
}

# What the servers' own database role may do when migrations run as the table owner: change
# data, append to the ledger, and nothing else (PostgreSQL; see docs/operations.md).
_APP_GRANTS = (
    "GRANT SELECT ON metis_schema TO {role}",
    "GRANT SELECT, INSERT, UPDATE ON metis_workspaces, chap_workspaces, metis_members TO {role}",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON metis_outbox, metis_chat_identities TO {role}",
    "GRANT SELECT, INSERT ON metis_evidence_ledger TO {role}",
)
_ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

# PostgreSQL errors that mean "the workspace is busy": a lock or statement timeout.
_BUSY_SQLSTATES = {"55P03", "57014"}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def normalise_url(url: str) -> str:
    """Use the psycopg 3 driver for PostgreSQL URLs that name no driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _create_db(url: str, echo: bool = False, *, pool_size: int = 5,
               max_overflow: int = 10) -> Engine:
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
            # Metis begins every transaction itself (below), so reads see one snapshot and
            # schema changes are atomic.
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout = 10000")
            # A REPLACE into the ledger fires its delete trigger, and is refused.
            cursor.execute("PRAGMA recursive_triggers = ON")
            if not memory:
                cursor.execute("PRAGMA journal_mode = WAL")
            cursor.close()

        @event.listens_for(db, "begin")
        def _sqlite_begin(conn: Connection) -> None:
            read = conn.get_execution_options().get("metis_read")
            conn.exec_driver_sql("BEGIN" if read else "BEGIN IMMEDIATE")

        return db
    return create_engine(url, echo=echo, pool_pre_ping=True, isolation_level="READ COMMITTED",
                         pool_size=pool_size, max_overflow=max_overflow)


def _advisory_key(workspace_id: str) -> int:
    digest = hashlib.sha256(f"metis:{workspace_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _busy(exc: DBAPIError) -> bool:
    if getattr(exc.orig, "sqlstate", None) in _BUSY_SQLSTATES:
        return True
    return "database is locked" in str(exc.orig).lower()


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


def _members_of(engine: MetisEngine) -> dict[str, list[str]]:
    return {uri: [r.value for r in m.roles] for uri, m in engine.members.items() if m.roles}


def _digest(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


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
    """The append-only evidence ledger of one workspace, in ``metis_evidence_ledger``.

    The ledger and the CHAP snapshot are committed together, so a restored workspace's chain
    must hold exactly the ledger's entries: any difference is reported as a mismatch, never
    repaired by copying entries across.
    """

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

    @staticmethod
    def _record(adapter: Any, entry: Any) -> str:
        return json.dumps(adapter.evidence_record(entry), separators=(",", ":"))

    def sync(self, adapter: Any) -> int:
        """Append every chain entry the ledger does not hold yet; return how many. The entries
        already held must be the chain's own, checked at the last one."""
        self.check(adapter, exact=False)
        new = adapter.chain.entries[self.count:]
        if not new:
            return 0
        if self.read_only:
            raise PermissionError(f"{self.path} was opened read-only.")
        now = _now()
        self._conn().execute(insert(ledger_table), [
            {"workspace_id": self.workspace_id, "seq": entry.seq,
             "record": self._record(adapter, entry), "recorded_at": now} for entry in new])
        self._count = self.count + len(new)
        return len(new)

    def matches(self, adapter: Any) -> bool:
        stored = [json.loads(self._record(adapter, e)) for e in adapter.chain.entries]
        return self.records() == stored

    def check(self, adapter: Any, *, exact: bool = True) -> None:
        """Raise ``LedgerMismatch`` unless the ledger holds the chain's entries: all of them
        (``exact``), or a prefix of them, compared at the last entry it holds."""
        entries = adapter.chain.entries
        if self.count > len(entries) or (exact and self.count != len(entries)):
            raise LedgerMismatch(f"{self.path} holds {self.count} entries but the CHAP store "
                                 f"holds {len(entries)}.")
        if self.count:
            last = self._conn().execute(
                select(ledger_table.c.record).where(ledger_table.c.workspace_id == self.workspace_id)
                .order_by(ledger_table.c.seq.desc()).limit(1)).scalar_one()
            if json.loads(last) != json.loads(self._record(adapter, entries[self.count - 1])):
                raise LedgerMismatch(f"{self.path} disagrees with the CHAP store at entry "
                                     f"{self.count - 1}.")


# ---- the repository ------------------------------------------------------------------------
@dataclass
class _Cached:
    engine: MetisEngine
    version: int
    write_id: str | None
    state_digest: str
    chain_count: int
    members: dict[str, list[str]]


class SqlRepository:
    """Workspaces in PostgreSQL or SQLite, with one writer per workspace.

    ``url`` is a SQLAlchemy URL: ``postgresql://user:pass@host/db`` (psycopg 3) or
    ``sqlite:///path/metis.db``. ``engine_options`` are passed to every ``MetisEngine`` built
    (for example ``use_live_model``). With ``migrate`` the schema is created or upgraded on
    start; without it, the schema is only checked (run ``metis server migrate`` separately).
    """

    def __init__(self, url: str, *, echo: bool = False, cache_size: int = 64,
                 engine_options: dict[str, Any] | None = None, migrate: bool = True,
                 notifier: Any = None, lock_timeout: float = 30.0,
                 statement_timeout: float = 60.0, pool_size: int = 5,
                 max_overflow: int = 10, app_role: str | None = None) -> None:
        self.url = normalise_url(url)
        # A metis.notify.Notifier: plans notifications inside each write's transaction.
        self.notifier = notifier if notifier is not None and notifier.enabled else None
        self.db = _create_db(self.url, echo=echo, pool_size=pool_size, max_overflow=max_overflow)
        self.dialect = self.db.dialect.name
        self._shared_connection = self.url in ("sqlite://", "sqlite:///:memory:")
        # Reads see one snapshot of the database.
        self.reader = (self.db.execution_options(isolation_level="REPEATABLE READ")
                       if self.dialect == "postgresql" else self.db.execution_options(metis_read=True))
        self.engine_options = dict(engine_options or {})
        self.cache_size = max(1, cache_size)
        if app_role and not _ROLE_NAME.match(app_role):
            raise ValueError(f"Not a database role name: {app_role!r}")
        self.app_role = app_role
        self.lock_timeout = max(0.1, float(lock_timeout))
        self.statement_timeout = max(1.0, float(statement_timeout))
        self._cache: OrderedDict[str, _Cached] = OrderedDict()
        self._cache_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._sqlite_lock = threading.RLock()
        if migrate:
            self.migrate()
        else:
            self.check_schema()

    # -- schema --
    @staticmethod
    def _schema_version(conn: Connection) -> tuple[int | None, int | None]:
        """The stored schema version and its compatibility floor, or ``(None, None)``."""
        found = inspect(conn)
        if not found.has_table("metis_schema"):
            return None, None
        columns = {c["name"] for c in found.get_columns("metis_schema")}
        if "min_compatible" in columns:
            row = conn.execute(select(schema_table.c.version, schema_table.c.min_compatible)).first()
        else:
            row = conn.execute(select(schema_table.c.version)).first()
        if row is None:
            return None, None
        return row[0], (row[1] if len(row) > 1 else None)

    @staticmethod
    def _refuse_newer(version: int, floor: int | None) -> bool:
        """True when a database at ``version`` is newer than this code and incompatible."""
        if version <= SCHEMA_VERSION:
            return False
        if (floor or version) > SCHEMA_VERSION:
            raise SchemaTooNew(
                f"The database schema is version {version} and needs Metis that knows schema "
                f"{floor or version} or later; this Metis knows up to {SCHEMA_VERSION}. Upgrade "
                "Metis, or restore the backup taken before the upgrade.")
        return True

    def migrate(self) -> int:
        """Create or upgrade the schema; return its version. Safe to run from several
        processes at once: on PostgreSQL an advisory lock serialises them, and every change is
        made in one transaction. A database from a newer, compatible Metis is left as it is."""
        with self._writer(), self.db.begin() as conn:
            if self.dialect == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                             {"key": _advisory_key("__schema__")})
            version, floor = self._schema_version(conn)
            if version is not None and self._refuse_newer(version, floor):
                return version
            metadata.create_all(conn)
            if version is not None and version < SCHEMA_VERSION:
                self._upgrade(conn, version)
            self._ensure_triggers(conn)
            self._grant_app_role(conn)
            if version is None:
                conn.execute(insert(schema_table).values(version=SCHEMA_VERSION,
                                                         min_compatible=MIN_COMPATIBLE))
            elif version < SCHEMA_VERSION:
                conn.execute(update(schema_table).values(version=SCHEMA_VERSION,
                                                         min_compatible=MIN_COMPATIBLE))
        return SCHEMA_VERSION

    def check_schema(self) -> int:
        """The schema version, provided this Metis can use it; for servers that leave
        migrations to ``metis server migrate``."""
        with self._reader_lock(), self.reader.connect() as conn:
            version, floor = self._schema_version(conn)
        if version is None:
            raise StorageCorruption("The database has no Metis schema; run `metis server migrate`.")
        if version < SCHEMA_VERSION:
            raise StorageCorruption(f"The database schema is version {version}; this Metis needs "
                                    f"{SCHEMA_VERSION}. Run `metis server migrate`.")
        self._refuse_newer(version, floor)
        return version

    def _upgrade(self, conn: Connection, version: int) -> None:
        """Bring tables that existed at ``version`` up to date (new tables were just created)."""
        found = inspect(conn)
        for table, column, kind in _ADDED_COLUMNS:
            if found.has_table(table) and column not in {c["name"] for c in found.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {kind}"))
        if version < 4:  # every workspace gets a commit token and a membership index
            for row in conn.execute(select(workspaces_table.c.id, workspaces_table.c.state)).all():
                conn.execute(update(workspaces_table).where(workspaces_table.c.id == row.id)
                             .values(write_id=uuid.uuid4().hex))
                state = json.loads(row.state)
                members = {m["uri"]: list(m.get("roles") or [])
                           for m in state.get("members") or [] if m.get("roles")}
                self._sync_members(conn, row.id, members)
                # Contributors who are no longer members stay able to withdraw their consent.
                former = {uri for f in state.get("fragments") or [] for uri in (
                    (f.get("provenance") or {}).get("originating_participant"),
                    (f.get("provenance") or {}).get("observed_by"),
                    (f.get("provenance") or {}).get("human_confirmed_by"),
                    (f.get("attribution") or {}).get("worker_or_group"))
                    if isinstance(uri, str) and uri.startswith("human:")} - set(members)
                for uri in sorted(former):
                    conn.execute(insert(members_table).values(
                        workspace_id=row.id, participant=uri, roles="[]", updated_at=_now()))

    def _grant_app_role(self, conn: Connection) -> None:
        """Give the servers' own role (``app_role``) what it needs and no more."""
        if self.dialect != "postgresql" or not self.app_role:
            return
        role = f'"{self.app_role}"'
        for statement in _APP_GRANTS:
            conn.execute(text(statement.format(role=role)))
        sequence = conn.execute(text("SELECT pg_get_serial_sequence('metis_outbox', 'id')")).scalar()
        if sequence:
            conn.execute(text(f"GRANT USAGE, SELECT ON SEQUENCE {sequence} TO {role}"))

    def _ensure_triggers(self, conn: Connection) -> None:
        """Create the ledger's append-only triggers where they are missing. Existing triggers
        are left alone, so a start changes no table when the schema is current."""
        if self.dialect == "sqlite":
            for statement in _SQLITE_TRIGGERS:
                conn.execute(text(statement))
        elif self.dialect == "postgresql":
            have = set(conn.execute(text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'metis_evidence_ledger'::regclass "
                "AND NOT tgisinternal")).scalars())
            missing = [name for name in _POSTGRES_TRIGGERS if name not in have]
            if missing:
                conn.execute(text(_POSTGRES_FUNCTION))
                for name in missing:
                    conn.execute(text(_POSTGRES_TRIGGERS[name]))

    def model_client(self) -> Any:
        """A client for the configured live local model, for drafting before a workspace is
        locked; ``None`` when engines use deterministic drafts (no model call to wait for)."""
        if not self.engine_options.get("use_live_model"):
            return None
        from ..models.model_config import ModelConfig
        from ..models.ollama_client import OllamaClient

        return OllamaClient(self.engine_options.get("model_config") or ModelConfig(),
                            deterministic=False)

    def ping(self) -> bool:
        """The database answers; takes no workspace lock."""
        with self._reader_lock(), self.reader.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True

    def close(self) -> None:
        with self._cache_guard:
            self._cache.clear()
        self.db.dispose()

    # -- locks and cache --
    def _acquire(self, lock: threading.RLock, what: str) -> None:
        if not lock.acquire(timeout=self.lock_timeout):
            raise WorkspaceBusy(f"{what} is busy; try again shortly.")

    def _reader_lock(self) -> Any:
        """In-memory SQLite shares one connection between threads, so its reads wait for the
        writer; a database file and PostgreSQL read concurrently."""
        return self._writer() if self._shared_connection else nullcontext()

    @contextmanager
    def _writer(self) -> Iterator[None]:
        """SQLite's one writer for the whole database; PostgreSQL needs no process lock."""
        if self.dialect != "sqlite":
            yield
            return
        self._acquire(self._sqlite_lock, "The database")
        try:
            yield
        finally:
            self._sqlite_lock.release()

    def _lock_for(self, workspace_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(workspace_id, threading.RLock())

    @contextmanager
    def _workspace_lock(self, workspace_id: str) -> Iterator[None]:
        lock = self._lock_for(workspace_id)
        self._acquire(lock, workspace_id)
        try:
            yield
        finally:
            lock.release()

    def _db_lock(self, conn: Connection, workspace_id: str) -> None:
        if self.dialect == "postgresql":
            ms = int(self.lock_timeout * 1000)
            conn.execute(text(
                "SELECT set_config('lock_timeout', :lock, true), "
                "set_config('statement_timeout', :stmt, true), "
                "set_config('idle_in_transaction_session_timeout', :idle, true)"),
                {"lock": f"{ms}ms", "stmt": f"{int(self.statement_timeout * 1000)}ms",
                 "idle": f"{int(self.statement_timeout * 2000)}ms"})
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                         {"key": _advisory_key(workspace_id)})

    def _cached(self, workspace_id: str, version: int, write_id: str | None) -> _Cached | None:
        with self._cache_guard:
            entry = self._cache.get(workspace_id)
            if entry is None or entry.version != version or entry.write_id != write_id:
                return None
            self._cache.move_to_end(workspace_id)
            return entry

    def _remember(self, workspace_id: str, entry: _Cached) -> None:
        with self._cache_guard:
            self._cache[workspace_id] = entry
            self._cache.move_to_end(workspace_id)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    def _forget(self, workspace_id: str) -> None:
        with self._cache_guard:
            self._cache.pop(workspace_id, None)

    @contextmanager
    def exclusive(self, name: str) -> Iterator[bool]:
        """Whether this process may run ``name`` now while no other process does (for example
        the background sweep). PostgreSQL decides with a session advisory lock; SQLite has one
        server process, so it always may."""
        if self.dialect != "postgresql":
            yield True
            return
        key = {"key": _advisory_key(f"exclusive:{name}")}
        with self.db.connect() as conn:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), key).scalar())
            conn.commit()
            try:
                yield got
            finally:
                if got:
                    conn.execute(text("SELECT pg_advisory_unlock(:key)"), key)
                    conn.commit()

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

    def _engine_for(self, conn: Connection, workspace_id: str, row: Any) -> _Cached:
        """The workspace's engine as committed at ``row``: from the cache when the commit token
        matches, otherwise rebuilt and checked from the database."""
        entry = self._cached(workspace_id, row.version, row.write_id)
        if entry is not None:
            self._bind(entry.engine, conn)
            return entry
        state_text = conn.execute(select(workspaces_table.c.state)
                                  .where(workspaces_table.c.id == workspace_id)).scalar_one()
        chap_version = conn.execute(select(chap_table.c.version)
                                    .where(chap_table.c.id == workspace_id)).scalar()
        if chap_version is None:
            raise StorageCorruption(f"{workspace_id} has no CHAP chain in chap_workspaces.")
        try:
            state = json.loads(state_text)
            if not isinstance(state, dict):
                raise ValueError("the stored state is not an object")
        except ValueError as exc:
            raise StorageCorruption(f"{workspace_id}: the stored domain state cannot be read "
                                    f"({exc.__class__.__name__}).") from exc
        engine = self._new_engine(
            conn, workspace_id, name=row.name, site=row.site,
            escalation_assignee=state.get("escalation_assignee"),
            review_rule=state.get("review_rule"),
            **({"whisper_deadline_ms": state["whisper_deadline_ms"]}
               if state.get("whisper_deadline_ms") else {}))
        chain = engine.adapter.chain
        if chain.count != chap_version:
            # The coordinator could not restore the stored chain and started another.
            raise StorageCorruption(f"{workspace_id}: the stored CHAP chain could not be restored.")
        described = state.get("workspace") or {}
        head = engine.adapter.descriptor()["evidence_head"]
        if (described.get("evidence_count") not in (None, chain.count)
                or described.get("evidence_head") not in (None, head)):
            raise StorageCorruption(f"{workspace_id}: the domain state and the CHAP chain are "
                                    "from different commits.")
        if not engine.verify().ok:
            raise StorageCorruption(f"{workspace_id}: the stored CHAP chain fails verification.")
        try:
            engine.import_state(state)
        except StateTooNew as exc:
            raise SchemaTooNew(f"{workspace_id}: {exc}") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise StorageCorruption(f"{workspace_id}: the stored domain state cannot be loaded "
                                    f"({exc.__class__.__name__}).") from exc
        return _Cached(engine=engine, version=row.version, write_id=row.write_id,
                       state_digest=_digest(state_text), chain_count=chain.count,
                       members=_members_of(engine))

    def _sync_members(self, conn: Connection, workspace_id: str,
                      members: dict[str, list[str]]) -> None:
        """Make the membership index match ``members``; someone no longer a member stays
        listed with no roles, as a former member."""
        t = members_table
        stored = {r.participant: json.loads(r.roles) for r in conn.execute(
            select(t.c.participant, t.c.roles).where(t.c.workspace_id == workspace_id))}
        now = _now()
        for uri in set(stored) | set(members):
            roles = members.get(uri, [])
            if uri not in stored:
                conn.execute(insert(t).values(workspace_id=workspace_id, participant=uri,
                                              roles=json.dumps(roles), updated_at=now))
            elif stored[uri] != roles:
                conn.execute(update(t).where(t.c.workspace_id == workspace_id,
                                             t.c.participant == uri)
                             .values(roles=json.dumps(roles), updated_at=now))

    def _save(self, conn: Connection, entry: _Cached, workspace_id: str) -> _Cached:
        """Commit the engine's changes; a write that changed nothing commits nothing."""
        engine = entry.engine
        state = json.dumps(engine.export_state(), sort_keys=True)
        digest, count = _digest(state), engine.adapter.chain.count
        if digest == entry.state_digest and count == entry.chain_count:
            return entry
        self._persist(engine)
        write_id = uuid.uuid4().hex
        result = conn.execute(
            update(workspaces_table)
            .where(workspaces_table.c.id == workspace_id,
                   workspaces_table.c.version == entry.version)
            .values(version=entry.version + 1, write_id=write_id, state=state,
                    name=engine.adapter.name, updated_at=_now()))
        if result.rowcount != 1:
            raise WorkspaceConflict(f"{workspace_id} was changed by another writer.")
        members = _members_of(engine)
        if members != entry.members:
            self._sync_members(conn, workspace_id, members)
        return _Cached(engine=engine, version=entry.version + 1, write_id=write_id,
                       state_digest=digest, chain_count=count, members=members)

    # -- notifications --
    def _observe_new(self) -> Any:
        if self.notifier is None:
            return None
        from ..notify.planner import WorkspaceView

        return WorkspaceView(chain=0)

    def _notify(self, conn: Connection, engine: MetisEngine, before: Any) -> None:
        """Write the notifications this transaction's changes call for to the outbox."""
        if self.notifier is None or before is None:
            return
        from ..notify.outbox import insert_rows

        insert_rows(conn, outbox_table, self.notifier.rows(self.notifier.plan(engine, before)),
                    skip_duplicates=False)

    def enqueue(self, notifications: list[Any]) -> int:
        """Add notifications outside a workspace write (for example review-date notices);
        a notification whose dedupe key was queued before is skipped."""
        if self.notifier is None or not notifications:
            return 0
        from ..notify.outbox import insert_rows

        with self._writer(), self.db.begin() as conn:
            return insert_rows(conn, outbox_table, self.notifier.rows(notifications),
                               skip_duplicates=True)

    def save_chat_identity(self, platform: str, participant: str, external_id: str,
                           reference: dict[str, Any]) -> None:
        """Remember where ``participant`` can be reached in a chat tool."""
        values = {"external_id": external_id, "reference": json.dumps(reference, sort_keys=True),
                  "updated_at": _now()}
        t = chat_identities_table
        with self._writer(), self.db.begin() as conn:
            result = conn.execute(update(t).where(t.c.platform == platform,
                                                  t.c.participant == participant).values(**values))
            if result.rowcount == 0:
                conn.execute(insert(t).values(platform=platform, participant=participant, **values))

    def forget_chat_identity(self, platform: str, external_id: str | None = None, *,
                             participant: str | None = None) -> int:
        """Forget where someone was reached: after they removed the app (by their id in the
        chat tool), or so another account may be bound to them (by participant)."""
        t = chat_identities_table
        which = (t.c.external_id == external_id) if external_id is not None else (
            t.c.participant == participant)
        with self._writer(), self.db.begin() as conn:
            return conn.execute(t.delete().where(t.c.platform == platform, which)).rowcount

    def chat_identity(self, platform: str, participant: str) -> dict[str, Any] | None:
        t = chat_identities_table
        with self._reader_lock(), self.reader.connect() as conn:
            row = conn.execute(select(t).where(t.c.platform == platform,
                                               t.c.participant == participant)).first()
        if row is None:
            return None
        return {"participant": row.participant, "external_id": row.external_id,
                **json.loads(row.reference)}

    def chat_participant(self, platform: str, external_id: str) -> str | None:
        t = chat_identities_table
        with self._reader_lock(), self.reader.connect() as conn:
            return conn.execute(select(t.c.participant).where(
                t.c.platform == platform, t.c.external_id == external_id)).scalar()

    def outbox(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Outbox rows, newest first, optionally of one status."""
        query = select(outbox_table).order_by(outbox_table.c.id.desc()).limit(limit)
        if status:
            query = query.where(outbox_table.c.status == status)
        with self._reader_lock(), self.reader.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(query)]

    def outbox_counts(self) -> dict[str, int]:
        """How many outbox rows are in each status."""
        t = outbox_table
        with self._reader_lock(), self.reader.connect() as conn:
            return {status: n for status, n in conn.execute(
                select(t.c.status, func.count()).group_by(t.c.status))}

    def outbox_oldest_pending(self) -> str | None:
        """When the oldest notification still awaiting delivery was queued."""
        t = outbox_table
        with self._reader_lock(), self.reader.connect() as conn:
            return conn.execute(select(func.min(t.c.created_at))
                                .where(t.c.status.in_(("pending", "sending")))).scalar()

    # -- public operations --
    def create(self, settings: WorkspaceSettings, *, by: str) -> dict[str, Any]:
        """Create a workspace with its system participants and initial members."""
        workspace_id = settings.id
        with self._workspace_lock(workspace_id):
            try:
                with self._writer(), self._timeouts_as_busy(workspace_id), self.db.begin() as conn:
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
                    before = self._observe_new()
                    for member in settings.members:
                        engine.set_member(member.uri, list(member.roles), by=by,
                                          display_name=member.display_name,
                                          reason="initial member")
                    self._persist(engine)
                    self._notify(conn, engine, before)
                    now, write_id = _now(), uuid.uuid4().hex
                    state = json.dumps(engine.export_state(), sort_keys=True)
                    conn.execute(insert(workspaces_table).values(
                        id=workspace_id, name=settings.name, site=settings.site, version=1,
                        write_id=write_id, state=state, created_at=now, updated_at=now))
                    members = _members_of(engine)
                    self._sync_members(conn, workspace_id, members)
                    descriptor = engine.adapter.descriptor()
                    self._bind(engine, None)
            except BaseException:
                self._forget(workspace_id)
                raise
            self._remember(workspace_id, _Cached(
                engine=engine, version=1, write_id=write_id, state_digest=_digest(state),
                chain_count=engine.adapter.chain.count, members=members))
            return descriptor

    def list(self) -> list[WorkspaceSummary]:
        with self._reader_lock(), self.reader.connect() as conn:
            rows = conn.execute(select(
                workspaces_table.c.id, workspaces_table.c.name, workspaces_table.c.site,
                workspaces_table.c.created_at, workspaces_table.c.updated_at,
                workspaces_table.c.version).order_by(workspaces_table.c.id)).all()
        return [WorkspaceSummary(id=r.id, name=r.name, site=r.site, created_at=r.created_at,
                                 updated_at=r.updated_at, version=r.version) for r in rows]

    def memberships(self, uri: str) -> dict[str, list[str]]:
        """The workspaces ``uri`` is a member of, with its roles in each, from committed state."""
        t = members_table
        with self._reader_lock(), self.reader.connect() as conn:
            rows = conn.execute(select(t.c.workspace_id, t.c.roles)
                                .where(t.c.participant == uri)
                                .order_by(t.c.workspace_id)).all()
        return {r.workspace_id: roles for r in rows if (roles := json.loads(r.roles))}

    def member_roles(self, workspace_id: str, uri: str) -> list[str] | None:
        """``uri``'s roles in the workspace: a list (empty for a former member), or ``None``
        when ``uri`` has never been a member or the workspace does not exist."""
        t = members_table
        with self._reader_lock(), self.reader.connect() as conn:
            roles = conn.execute(select(t.c.roles).where(t.c.workspace_id == workspace_id,
                                                         t.c.participant == uri)).scalar()
        return None if roles is None else json.loads(roles)

    def exists(self, workspace_id: str) -> bool:
        with self._reader_lock(), self.reader.connect() as conn:
            return conn.execute(select(workspaces_table.c.id)
                                .where(workspaces_table.c.id == workspace_id)).first() is not None

    def _row(self, conn: Connection, workspace_id: str) -> Any:
        row = conn.execute(select(
            workspaces_table.c.version, workspaces_table.c.write_id, workspaces_table.c.name,
            workspaces_table.c.site).where(workspaces_table.c.id == workspace_id)).first()
        if row is None:
            raise UnknownWorkspace(workspace_id)
        return row

    @contextmanager
    def _timeouts_as_busy(self, workspace_id: str) -> Iterator[None]:
        """Report the database's lock and statement timeouts as ``WorkspaceBusy``."""
        try:
            yield
        except DBAPIError as exc:
            if _busy(exc):
                raise WorkspaceBusy(f"{workspace_id} is busy; try again shortly.") from exc
            raise

    @staticmethod
    def _refusal(exc: BaseException) -> bool:
        """A refused or impossible request, raised before it changed anything: the cached
        engine stays valid."""
        if isinstance(exc, PermissionError):
            return exc.errno is None
        return isinstance(exc, LookupError)

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
        with self._workspace_lock(workspace_id):
            entry: _Cached | None = None
            count = -1
            try:
                with self._writer(), self._timeouts_as_busy(workspace_id), self.db.begin() as conn:
                    self._db_lock(conn, workspace_id)
                    row = self._row(conn, workspace_id)
                    entry = self._engine_for(conn, workspace_id, row)
                    engine = entry.engine
                    count = engine.adapter.chain.count
                    try:
                        before = self.notifier.observe(engine) if self.notifier else None
                        result = fn(engine)
                        saved = self._save(conn, entry, workspace_id)
                        self._notify(conn, engine, before)
                    finally:
                        engine.adapter.store.discard()
                        self._bind(engine, None)
            except BaseException as exc:
                if (entry is not None and entry.engine.adapter.chain.count == count
                        and self._refusal(exc)):
                    self._remember(workspace_id, entry)
                else:
                    self._forget(workspace_id)
                raise
            self._remember(workspace_id, saved)
            return result

    def read(self, workspace_id: str, fn: Callable[[MetisEngine], T]) -> T:
        """Run ``fn`` against the committed state of the workspace; it must record nothing."""
        with self._workspace_lock(workspace_id):
            entry: _Cached | None = None
            before = -1
            try:
                with self._reader_lock(), self.reader.connect() as conn:  # rolls back: writes nothing
                    row = self._row(conn, workspace_id)
                    entry = self._engine_for(conn, workspace_id, row)
                    engine = entry.engine
                    before = engine.adapter.chain.count
                    try:
                        result = fn(engine)
                    finally:
                        self._bind(engine, None)
                    if engine.adapter.chain.count != before:
                        raise RuntimeError("A read recorded evidence; use write for this operation.")
            except BaseException as exc:
                if (entry is not None and entry.engine.adapter.chain.count == before
                        and self._refusal(exc)):
                    self._remember(workspace_id, entry)
                else:
                    self._forget(workspace_id)
                raise
            self._remember(workspace_id, entry)
            return result
