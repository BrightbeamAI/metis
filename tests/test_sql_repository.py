"""The SQL workspace repository: transactions, one writer, restarts, and append-only evidence.

Runs on SQLite. Set METIS_TEST_DATABASE_URL (for example
postgresql://metis:metis@localhost:5432/metis_test) to run the same tests on PostgreSQL.
"""
import dataclasses
import os
import threading

import pytest
from sqlalchemy import create_engine, text

from metis.conditions.context import TacitContext
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.governance.membership import Member, Role
from metis.storage.repository import (
    StorageCorruption,
    UnknownWorkspace,
    WorkspaceConflict,
    WorkspaceExists,
    WorkspaceSettings,
)
from metis.storage.sql import SqlRepository, normalise_url

ADMIN = "human:admin@example.com"
WORKER = "human:wendy@example.com"
R1, R2 = "human:rhea@example.com", "human:raj@example.com"
AGENT = "agent:shift-assistant"
PUMP = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load")
PG_URL = os.environ.get("METIS_TEST_DATABASE_URL")


def _reset_postgres(url: str) -> None:
    db = create_engine(normalise_url(url))
    with db.begin() as conn:
        for table in ("metis_evidence_ledger", "metis_workspaces", "chap_workspaces", "metis_schema"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        conn.execute(text("DROP FUNCTION IF EXISTS metis_ledger_append_only() CASCADE"))
    db.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def db_url(request, tmp_path):
    if request.param == "postgresql":
        if not PG_URL:
            pytest.skip("set METIS_TEST_DATABASE_URL to run on PostgreSQL")
        _reset_postgres(PG_URL)
        return PG_URL
    return f"sqlite:///{tmp_path / 'metis.db'}"


def _settings(**kw) -> WorkspaceSettings:
    members = [Member(uri=WORKER, roles=[Role.worker]), Member(uri=R1, roles=[Role.reviewer]),
               Member(uri=R2, roles=[Role.reviewer]), Member(uri=AGENT, roles=[Role.agent])]
    return WorkspaceSettings(id="wsp_plant_a", name="Plant A", site="plant_a", members=members, **kw)


def _capture(engine, obs_id="OBS-1"):
    pending = engine.begin_capture(
        {"observation_id": obs_id, "work_as_done": "Ease back earlier on a dull sound.",
         "context": PUMP},
        consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=WORKER,
        category="K7_sensory", conditions=PUMP)
    return engine.answer_whisper(pending.whisper_id, response="confirm", answered_by=WORKER,
                                 consent_granted=True).fragment.fragment_id


def _promote(repo, fid):
    repo.write("wsp_plant_a", lambda e: e.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1))
    return repo.write("wsp_plant_a",
                      lambda e: e.cast_review_vote(fid, "promoted_to_advisory", reviewer=R2))


def test_create_list_and_describe(db_url):
    repo = SqlRepository(db_url)
    descriptor = repo.create(_settings(), by=ADMIN)
    assert descriptor["id"] == "wsp_plant_a" and descriptor["evidence_count"] > 0
    assert [w.id for w in repo.list()] == ["wsp_plant_a"] and repo.exists("wsp_plant_a")
    assert repo.read("wsp_plant_a", lambda e: e.mission_group_members) == [R1, R2]
    with pytest.raises(WorkspaceExists):
        repo.create(_settings(), by=ADMIN)
    with pytest.raises(UnknownWorkspace):
        repo.read("wsp_nowhere", lambda e: None)
    with pytest.raises(ValueError):
        WorkspaceSettings(id="Plant A", name="x")
    repo.close()


def test_a_restarted_server_continues_the_chain(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    fid = repo.write("wsp_plant_a", _capture)
    decided = _promote(repo, fid)
    assert decided["status"] == "decided"
    count = repo.read("wsp_plant_a", lambda e: e.adapter.chain.count)
    repo.close()

    restarted = SqlRepository(db_url)
    def inspect(engine):
        frag = engine.fragments.require(fid)
        return (frag.validation_state.value, engine.adapter.chain.count, engine.verify().ok,
                engine.adapter.ledger.matches(engine.adapter), engine.mission_group_members)
    state, again, ok, agrees, reviewers = restarted.read("wsp_plant_a", inspect)
    assert (state, again, ok, agrees, reviewers) == ("promoted_to_advisory", count, True, True, [R1, R2])
    decision = restarted.write("wsp_plant_a", lambda e: e.retrieve(PUMP, requester=AGENT))
    assert len(decision.eligible) == 1
    assert restarted.read("wsp_plant_a", lambda e: e.adapter.chain.count) > count
    restarted.close()


def test_a_failed_write_records_nothing(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    before = repo.read("wsp_plant_a", lambda e: (e.adapter.chain.count, len(e.fragments.all())))

    def capture_then_fail(engine):
        _capture(engine)
        raise RuntimeError("the network dropped")

    with pytest.raises(RuntimeError):
        repo.write("wsp_plant_a", capture_then_fail)
    after = repo.read("wsp_plant_a", lambda e: (e.adapter.chain.count, len(e.fragments.all())))
    assert after == before
    assert repo.write("wsp_plant_a", _capture)  # the next write starts from the committed state
    assert repo.read("wsp_plant_a", lambda e: e.adapter.ledger.matches(e.adapter))
    repo.close()


def test_a_read_cannot_record(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    before = repo.read("wsp_plant_a", lambda e: e.adapter.chain.count)
    with pytest.raises(RuntimeError):
        repo.read("wsp_plant_a", lambda e: e.retrieve(PUMP, requester=AGENT))
    assert repo.read("wsp_plant_a", lambda e: e.adapter.chain.count) == before
    repo.close()


def test_the_ledger_is_append_only(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    for statement in ("UPDATE metis_evidence_ledger SET record = '{}'",
                      "DELETE FROM metis_evidence_ledger"):
        with pytest.raises(Exception, match="append-only"):
            with repo.db.begin() as conn:
                conn.execute(text(statement))
    repo.close()


def test_a_conflicting_write_is_retried_on_fresh_state(db_url, monkeypatch):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    real_save, calls = SqlRepository._save, []

    def flaky_save(self, conn, entry, workspace_id):
        calls.append(entry.version)
        if len(calls) == 1:
            raise WorkspaceConflict("another writer")
        return real_save(self, conn, entry, workspace_id)

    monkeypatch.setattr(SqlRepository, "_save", flaky_save)
    fid = repo.write("wsp_plant_a", _capture)
    assert len(calls) == 2
    assert repo.read("wsp_plant_a", lambda e: e.fragments.require(fid).fragment_id) == fid
    monkeypatch.setattr(SqlRepository, "_save", real_save)

    with repo.db.begin() as conn:  # a stale version is refused
        entry = repo._engine_for(conn, "wsp_plant_a", repo._row(conn, "wsp_plant_a"))
        _capture(entry.engine, "OBS-STALE")
        with pytest.raises(WorkspaceConflict):
            repo._save(conn, dataclasses.replace(entry, version=0), "wsp_plant_a")
        conn.rollback()
    repo.close()


def test_concurrent_writes_are_serialised(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    fid = repo.write("wsp_plant_a", _capture)
    _promote(repo, fid)
    before = repo.read("wsp_plant_a", lambda e: e.adapter.chain.count)
    errors: list[BaseException] = []

    def ask():
        try:
            repo.write("wsp_plant_a", lambda e: e.retrieve(PUMP, requester=AGENT))
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    per_retrieval = repo.write("wsp_plant_a", lambda e: (
        lambda n: (e.retrieve(PUMP, requester=AGENT), e.adapter.chain.count - n))(e.adapter.chain.count))[1]
    count, ok, agrees = repo.read("wsp_plant_a", lambda e: (
        e.adapter.chain.count, e.verify().ok, e.adapter.ledger.matches(e.adapter)))
    assert count == before + 9 * per_retrieval and ok and agrees
    repo.close()


def test_the_stored_snapshot_is_chap_s_own(db_url):
    """One snapshot per transaction, byte for byte the JSON CHAP's own stores write."""
    import dataclasses
    import json

    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    fid = repo.write("wsp_plant_a", _capture)
    _promote(repo, fid)

    def compare(engine):
        ws = engine.adapter.coord.get_workspace("wsp_plant_a")
        return json.dumps(dataclasses.asdict(ws), sort_keys=True), len(ws.audit)
    expected, version = repo.read("wsp_plant_a", compare)
    with repo.db.connect() as conn:
        row = conn.execute(text("SELECT data, version FROM chap_workspaces")).one()
    assert row.data == expected and row.version == version
    assert repo.read("wsp_plant_a", lambda e: e.adapter.coord.options.store) is None
    repo.close()


def test_a_damaged_chain_is_refused(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    repo.close()
    with SqlRepository(db_url).db.begin() as conn:
        conn.execute(text("UPDATE chap_workspaces SET data = '{\"broken\": true}'"))
    damaged = SqlRepository(db_url)
    from metis.audit.ledger import LedgerMismatch
    with pytest.raises((StorageCorruption, LedgerMismatch)):
        damaged.read("wsp_plant_a", lambda e: e.adapter.chain.count)
    damaged.close()


def _make_version_3(db_url):
    """Reshape a current database into the version 3 schema: no commit tokens, no membership
    index, no compatibility floor, no outbox leases."""
    db = create_engine(normalise_url(db_url))
    with db.begin() as conn:
        conn.execute(text("DROP TABLE metis_members"))
        for table, keep in (
                ("metis_workspaces", "id, name, site, version, state, created_at, updated_at"),
                ("metis_outbox", "id, workspace_id, event, channel, recipient, payload, dedupe_key, "
                                 "status, attempts, next_attempt_at, created_at, delivered_at, "
                                 "last_error")):
            conn.execute(text(f"CREATE TABLE old_{table} AS SELECT {keep} FROM {table}"))
            conn.execute(text(f"DROP TABLE {table}"))
            conn.execute(text(f"ALTER TABLE old_{table} RENAME TO {table}"))
        conn.execute(text("DROP TABLE metis_schema"))
        conn.execute(text("CREATE TABLE metis_schema (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO metis_schema (version) VALUES (3)"))
    db.dispose()


def _schema_row(db_url):
    db = create_engine(normalise_url(db_url))
    with db.connect() as conn:
        row = conn.execute(text("SELECT version, min_compatible FROM metis_schema")).one()
    db.dispose()
    return tuple(row)


def test_an_older_database_is_upgraded(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    repo.close()
    _make_version_3(db_url)
    upgraded = SqlRepository(db_url)
    assert upgraded.migrate() == 4 and _schema_row(db_url) == (4, 4)
    with upgraded.db.connect() as conn:
        assert conn.execute(text("SELECT write_id FROM metis_workspaces")).scalar()
    assert upgraded.memberships(R1) == {"wsp_plant_a": ["reviewer"]}
    assert upgraded.outbox() == []
    assert upgraded.read("wsp_plant_a", lambda e: e.mission_group_members) == [R1, R2]
    upgraded.close()


def test_a_newer_schema_is_used_only_when_compatible(db_url):
    from metis.storage.repository import SchemaTooNew

    SqlRepository(db_url).close()
    db = create_engine(normalise_url(db_url))
    with db.begin() as conn:  # a newer release that only added to the schema
        conn.execute(text("UPDATE metis_schema SET version = 9, min_compatible = 4"))
    compatible = SqlRepository(db_url)
    assert compatible.migrate() == 9 and _schema_row(db_url) == (9, 4)
    compatible.close()
    with db.begin() as conn:  # a newer release this one cannot use: refused before any change
        conn.execute(text("DROP TABLE metis_chat_identities"))
        conn.execute(text("UPDATE metis_schema SET min_compatible = 7"))
    with pytest.raises(SchemaTooNew, match="restore the backup"):
        SqlRepository(db_url)
    with db.connect() as conn:
        assert not db.dialect.has_table(conn, "metis_chat_identities")
    db.dispose()


def test_without_migrating_on_start_the_schema_is_only_checked(db_url):
    with pytest.raises(StorageCorruption, match="metis server migrate"):
        SqlRepository(db_url, migrate=False)
    SqlRepository(db_url).close()
    checked = SqlRepository(db_url, migrate=False)
    assert checked.check_schema() == 4
    checked.close()


def test_the_ledger_refuses_a_replace(db_url):
    if not db_url.startswith("sqlite"):
        pytest.skip("INSERT OR REPLACE is SQLite's")
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    with pytest.raises(Exception, match="append-only"):
        with repo.db.begin() as conn:
            conn.execute(text("INSERT OR REPLACE INTO metis_evidence_ledger "
                              "(workspace_id, seq, record, recorded_at) "
                              "VALUES ('wsp_plant_a', 0, '{}', 'now')"))
    repo.close()


def test_unreadable_state_is_reported_as_corruption(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    repo.close()
    db = create_engine(normalise_url(db_url))
    with db.begin() as conn:
        conn.execute(text("UPDATE metis_workspaces SET state = '{\"broken'"))
    db.dispose()
    damaged = SqlRepository(db_url)
    with pytest.raises(StorageCorruption, match="cannot be read"):
        damaged.read("wsp_plant_a", lambda e: None)
    damaged.close()


def test_state_and_chain_from_different_commits_are_refused(db_url):
    from metis.audit.ledger import LedgerMismatch

    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    with repo.db.connect() as conn:
        old = conn.execute(text("SELECT state FROM metis_workspaces")).scalar()
    repo.write("wsp_plant_a", _capture)
    with repo.db.begin() as conn:  # the domain state goes back one commit; the chain does not
        conn.execute(text("UPDATE metis_workspaces SET state = :s, write_id = 'other'"), {"s": old})
    with pytest.raises((StorageCorruption, LedgerMismatch), match="different commits"):
        repo.read("wsp_plant_a", lambda e: None)
    repo.close()


def test_a_restored_database_is_never_overwritten_from_a_stale_cache(db_url, tmp_path):
    """After a restore, a replica's cached engine is stale even at the same version number."""
    if not db_url.startswith("sqlite"):
        pytest.skip("restores the SQLite file in place")
    import sqlite3

    path = db_url[len("sqlite:///"):]
    a = SqlRepository(db_url)
    a.create(_settings(), by=ADMIN)
    a.read("wsp_plant_a", lambda e: None)  # replica A caches the workspace
    backup = tmp_path / "backup.db"
    with sqlite3.connect(path) as live, sqlite3.connect(backup) as copy:
        live.backup(copy)
    a.write("wsp_plant_a", lambda e: _capture(e, "OBS-A"))  # A moves on, and caches that
    with sqlite3.connect(backup) as copy, sqlite3.connect(path) as live:
        copy.backup(live)  # the database is restored under the running replica
    b = SqlRepository(db_url)  # replica B commits different work at the same version
    b.write("wsp_plant_a", lambda e: _capture(e, "OBS-B"))
    a.write("wsp_plant_a", lambda e: _capture(e, "OBS-C"))  # A must rebuild, never overwrite
    seen = a.read("wsp_plant_a", lambda e: (
        [e.observation_seen(o) for o in ("OBS-A", "OBS-B", "OBS-C")], len(e.fragments.all()),
        e.verify().ok, e.adapter.ledger.matches(e.adapter)))
    # B's capture and A's new one; A's capture from before the restore is gone with it.
    assert seen == ([False, True, True], 2, True, True)
    a.close()
    b.close()


def test_refused_requests_keep_the_cached_engine(db_url, monkeypatch):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    repo.read("wsp_plant_a", lambda e: None)
    built = []
    real = SqlRepository._new_engine
    monkeypatch.setattr(SqlRepository, "_new_engine",
                        lambda self, *a, **kw: built.append(1) or real(self, *a, **kw))

    def refuse(engine):
        raise PermissionError("not for you")
    for _ in range(3):
        with pytest.raises(PermissionError):
            repo.read("wsp_plant_a", refuse)
        with pytest.raises(PermissionError):
            repo.write("wsp_plant_a", refuse)
    assert built == []
    repo.close()


def test_a_write_that_changes_nothing_commits_nothing(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    before = repo.list()[0].version
    repo.write("wsp_plant_a", lambda e: e.overdue_whispers(__import__("datetime").datetime.now(
        __import__("datetime").timezone.utc)))
    assert repo.list()[0].version == before
    repo.write("wsp_plant_a", _capture)
    assert repo.list()[0].version == before + 1
    repo.close()


def test_a_busy_workspace_answers_busy_in_time(db_url):
    from metis.storage.repository import WorkspaceBusy

    repo = SqlRepository(db_url, lock_timeout=0.2)
    repo.create(_settings(), by=ADMIN)
    held, release = threading.Event(), threading.Event()

    def hold(engine):
        held.set()
        release.wait(5)
    worker = threading.Thread(target=lambda: repo.write("wsp_plant_a", hold))
    worker.start()
    held.wait(5)
    try:
        with pytest.raises(WorkspaceBusy):
            repo.write("wsp_plant_a", lambda e: None)
        assert repo.ping()  # readiness never waits for a writer
    finally:
        release.set()
        worker.join()
    repo.close()


def test_the_membership_index_follows_the_members(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    assert repo.memberships(WORKER) == {"wsp_plant_a": ["worker"]}
    assert repo.member_roles("wsp_plant_a", AGENT) == ["agent"]
    assert repo.member_roles("wsp_plant_a", "human:nobody@example.com") is None
    repo.write("wsp_plant_a", lambda e: e.set_member(WORKER, [], by=ADMIN))
    assert repo.memberships(WORKER) == {}
    assert repo.member_roles("wsp_plant_a", WORKER) == []  # a former member
    with repo.exclusive("sweep") as mine:
        assert mine
    repo.close()


def test_a_read_that_recorded_before_refusing_is_not_kept(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    committed = repo.read("wsp_plant_a", lambda e: e.adapter.chain.count)

    def record_then_refuse(engine):
        engine.retrieve(PUMP, requester=AGENT)
        raise PermissionError("refused")
    with pytest.raises(PermissionError):
        repo.read("wsp_plant_a", record_then_refuse)
    assert repo.read("wsp_plant_a", lambda e: e.adapter.chain.count) == committed
    repo.close()


def test_the_upgrade_keeps_former_contributors_able_to_withdraw(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    repo.write("wsp_plant_a", _capture)
    repo.write("wsp_plant_a", lambda e: e.set_member(WORKER, [], by=ADMIN))
    repo.close()
    _make_version_3(db_url)
    upgraded = SqlRepository(db_url)
    assert upgraded.member_roles("wsp_plant_a", WORKER) == []  # a former member
    upgraded.close()


def test_an_in_memory_database_serves_concurrent_reads():
    repo = SqlRepository("sqlite://")
    repo.create(_settings(), by=ADMIN)
    errors = []

    def read():
        try:
            for _ in range(5):
                repo.read("wsp_plant_a", lambda e: e.adapter.chain.count)
                repo.memberships(WORKER)
        except Exception as exc:  # surfaced below
            errors.append(exc)
    threads = [threading.Thread(target=read) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    repo.close()
