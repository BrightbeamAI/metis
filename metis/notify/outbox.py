"""The notification outbox and its dispatcher.

Notifications are written to ``metis_outbox`` in the same transaction as the evidence they
report, so a notification exists only for committed work, and a crash loses none. The
dispatcher delivers rows in the background: it leases a batch, sends each one, and records the
outcome. A failed delivery is retried with growing delays, then marked failed for an operator
to inspect (``metis server outbox list --status failed``).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .channels import Channel, deliveries
from .events import Notification, now_utc, stamp
from .planner import Planner, WorkspaceView, observe

log = logging.getLogger("metis.notify")


class Notifier:
    """Plans notifications for a write and turns them into outbox rows, one per delivery."""

    def __init__(self, channels: list[Channel], *, public_url: str | None = None,
                 planner: Planner | None = None) -> None:
        self.channels = list(channels)
        self.public_url = public_url
        self.planner = planner or Planner()

    @property
    def enabled(self) -> bool:
        return bool(self.channels)

    def observe(self, engine: Any) -> WorkspaceView:
        return observe(engine)

    def plan(self, engine: Any, before: WorkspaceView) -> list[Notification]:
        return self.planner.plan(engine, before, observe(engine))

    def review_due(self, engine: Any, now: _dt.datetime) -> list[Notification]:
        return self.planner.review_due(engine, now)

    def rows(self, notifications: list[Notification]) -> list[dict[str, Any]]:
        now = stamp(now_utc())
        rows = []
        for n in notifications:
            for channel, recipient in deliveries(self.channels, n):
                key = f"{n.dedupe_key}|{channel.name}|{recipient or ''}" if n.dedupe_key else None
                rows.append({"workspace_id": n.workspace_id, "event": n.event,
                             "channel": channel.name, "recipient": recipient,
                             "payload": json.dumps(n.as_dict(), sort_keys=True),
                             "dedupe_key": key, "status": "pending", "attempts": 0,
                             "next_attempt_at": now, "created_at": now})
        return rows


def insert_rows(conn: Any, table: Any, rows: list[dict[str, Any]], *, skip_duplicates: bool) -> int:
    """Insert outbox rows; with ``skip_duplicates``, a row whose dedupe key exists is skipped."""
    if not rows:
        return 0
    if not skip_duplicates:
        conn.execute(insert(table), rows)
        return len(rows)
    written = 0
    for row in rows:
        try:
            with conn.begin_nested():
                conn.execute(insert(table).values(**row))
            written += 1
        except IntegrityError:
            continue
    return written


def backoff(attempts: int) -> _dt.timedelta:
    return _dt.timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


class Dispatcher:
    """Delivers outbox rows through the configured channels."""

    def __init__(self, repo: Any, channels: list[Channel], *, batch: int = 50,
                 lease_seconds: int = 120, max_attempts: int = 8) -> None:
        from ..storage.sql import outbox_table

        self.repo = repo
        self.table = outbox_table
        self.channels = {c.name: c for c in channels}
        self.batch = batch
        self.lease = _dt.timedelta(seconds=lease_seconds)
        self.max_attempts = max_attempts
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _claim(self, now: _dt.datetime) -> list[Any]:
        t = self.table
        with self.repo._global(), self.repo.db.begin() as conn:
            query = (select(t).where(t.c.status.in_(("pending", "sending")),
                                     t.c.next_attempt_at <= stamp(now))
                     .order_by(t.c.id).limit(self.batch))
            if self.repo.dialect == "postgresql":
                query = query.with_for_update(skip_locked=True)
            rows = conn.execute(query).all()
            if rows:
                conn.execute(update(t).where(t.c.id.in_([r.id for r in rows]))
                             .values(status="sending", next_attempt_at=stamp(now + self.lease)))
        return rows

    def _finish(self, row: Any, error: str | None, now: _dt.datetime) -> str:
        t = self.table
        attempts = row.attempts + 1
        if error is None:
            values: dict[str, Any] = {"status": "delivered", "attempts": attempts,
                                      "delivered_at": stamp(now), "last_error": None}
            outcome = "delivered"
        elif attempts >= self.max_attempts:
            values = {"status": "failed", "attempts": attempts, "last_error": error[:2000]}
            outcome = "failed"
        else:
            values = {"status": "pending", "attempts": attempts, "last_error": error[:2000],
                      "next_attempt_at": stamp(now + backoff(attempts))}
            outcome = "retrying"
        with self.repo._global(), self.repo.db.begin() as conn:
            conn.execute(update(t).where(t.c.id == row.id).values(**values))
        return outcome

    def run_once(self, now: _dt.datetime | None = None) -> dict[str, int]:
        """Deliver every row that is due; return how many were delivered, retried, or failed."""
        now = now or now_utc()
        counts = {"delivered": 0, "retrying": 0, "failed": 0}
        for row in self._claim(now):
            channel = self.channels.get(row.channel)
            error = None
            if channel is None:
                error = f"Channel {row.channel!r} is no longer configured."
            else:
                try:
                    notification = Notification.from_dict(json.loads(row.payload))
                    channel.deliver(notification, row.recipient, row.id)
                except Exception as exc:  # recorded on the row and retried
                    error = f"{exc.__class__.__name__}: {exc}"
            outcome = self._finish(row, error, now)
            counts[outcome] += 1
            if error:
                log.warning("notification %s via %s: %s (%s)", row.id, row.channel, error, outcome)
        return counts

    def start(self, interval: float) -> None:
        if self._thread is not None or interval <= 0:
            return

        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.run_once()
                except Exception:  # keep the dispatcher alive; the next pass retries
                    log.exception("notification dispatch failed")

        self._thread = threading.Thread(target=loop, name="metis-notify", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
