"""The SQL workspace repository: transactions, one writer, restarts, and append-only evidence.

Runs on SQLite. Set METIS_TEST_DATABASE_URL (for example
postgresql://metis:metis@localhost:5432/metis_test) to run the same tests on PostgreSQL.
"""
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

    def flaky_save(self, conn, engine, workspace_id, expected):
        calls.append(expected)
        if len(calls) == 1:
            raise WorkspaceConflict("another writer")
        return real_save(self, conn, engine, workspace_id, expected)

    monkeypatch.setattr(SqlRepository, "_save", flaky_save)
    fid = repo.write("wsp_plant_a", _capture)
    assert len(calls) == 2
    assert repo.read("wsp_plant_a", lambda e: e.fragments.require(fid).fragment_id) == fid
    monkeypatch.setattr(SqlRepository, "_save", real_save)

    with repo.db.begin() as conn:  # a stale version is refused
        engine = repo._engine_for(conn, "wsp_plant_a", repo._row(conn, "wsp_plant_a"))
        with pytest.raises(WorkspaceConflict):
            repo._save(conn, engine, "wsp_plant_a", expected=0)
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


def test_a_version_1_database_is_upgraded(db_url):
    repo = SqlRepository(db_url)
    repo.create(_settings(), by=ADMIN)
    with repo.db.begin() as conn:
        conn.execute(text("DROP TABLE metis_outbox"))
        conn.execute(text("UPDATE metis_schema SET version = 1"))
    repo.close()
    upgraded = SqlRepository(db_url)
    assert upgraded.migrate() == 2
    assert upgraded.outbox() == []
    assert upgraded.read("wsp_plant_a", lambda e: e.mission_group_members) == [R1, R2]
    upgraded.close()
