"""The notification outbox and its dispatcher.

Notifications are written to ``metis_outbox`` in the same transaction as the evidence they
report, so a notification exists only for committed work, and a crash loses none. The
dispatcher delivers rows in the background: it claims a batch of due rows, leases each row to
itself with a token just before sending it, and records the outcome only while the lease is
still its own. Every claim counts as an attempt. A failed delivery is retried with growing
delays, then marked failed for an operator to inspect (``metis server outbox list --status
failed``) and send again (``metis server outbox retry``). Delivery is at least once: a slow or
crashed dispatcher's rows are claimed again, so a receiver may see a notification twice.

Error text kept on a row or logged never includes a URL's path or query, where webhook URLs
carry their secrets.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
import threading
import uuid
from typing import Any

from sqlalchemy import and_, delete, insert, select, update
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


_URL = re.compile(r"(https?://)([^/?#\s'\"<>]+)([^\s'\"<>]*)", re.IGNORECASE)


def redact(text: str) -> str:
    """``text`` with every URL cut to its scheme and host: webhook URLs carry secrets in their
    path and query, and HTTP errors quote the URL."""
    def cut(m: re.Match[str]) -> str:
        host = m.group(2).rsplit("@", 1)[-1]  # drop any user:password@
        return f"{m.group(1)}{host}/[redacted]" if m.group(3) or host != m.group(2) else m.group(0)
    return _URL.sub(cut, text)


def prune(repo: Any, *, retention_days: int, now: _dt.datetime | None = None) -> int:
    """Clear delivered and failed notifications older than ``retention_days``: rows are
    deleted, except that a row whose dedupe key prevents a duplicate notice keeps the key and
    loses its content. Returns how many rows changed."""
    from ..storage.sql import outbox_table as t

    cutoff = stamp((now or now_utc()) - _dt.timedelta(days=retention_days))
    old = and_(t.c.status.in_(("delivered", "failed")), t.c.created_at < cutoff)
    with repo._writer(), repo.db.begin() as conn:
        removed = conn.execute(delete(t).where(old, t.c.dedupe_key.is_(None))).rowcount
        emptied = conn.execute(update(t).where(old, t.c.dedupe_key.is_not(None),
                                               t.c.payload != "{}")
                               .values(payload="{}", recipient=None, last_error=None)).rowcount
    return removed + emptied


def retry_failed(repo: Any, ids: list[int] | None = None) -> int:
    """Send failed notifications again from the first attempt; return how many."""
    from ..storage.sql import outbox_table as t

    query = update(t).where(t.c.status == "failed", t.c.payload != "{}")  # cleared rows stay
    if ids:
        query = query.where(t.c.id.in_(ids))
    with repo._writer(), repo.db.begin() as conn:
        return conn.execute(query.values(status="pending", attempts=0, lease_token=None,
                                         next_attempt_at=stamp(now_utc()))).rowcount


class Dispatcher:
    """Delivers outbox rows through the configured channels."""

    def __init__(self, repo: Any, channels: list[Channel], *, batch: int = 20,
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

    def _claim(self, now: _dt.datetime) -> list[tuple[Any, str]]:
        """Due rows, each now leased to this dispatcher with its own token, with the attempt
        counted."""
        t = self.table
        claimed: list[tuple[Any, str]] = []
        with self.repo._writer(), self.repo.db.begin() as conn:
            query = (select(t).where(t.c.status.in_(("pending", "sending")),
                                     t.c.next_attempt_at <= stamp(now))
                     .order_by(t.c.id).limit(self.batch))
            if self.repo.dialect == "postgresql":
                query = query.with_for_update(skip_locked=True)
            for row in conn.execute(query).all():
                token = uuid.uuid4().hex
                conn.execute(update(t).where(t.c.id == row.id).values(
                    status="sending", lease_token=token, attempts=row.attempts + 1,
                    next_attempt_at=stamp(now + self.lease)))
                claimed.append((row, token))
        return claimed

    def _leased(self, row: Any, token: str, values: dict[str, Any]) -> bool:
        """Update the row while it is still leased to ``token``; False when it is not."""
        t = self.table
        with self.repo._writer(), self.repo.db.begin() as conn:
            return conn.execute(update(t).where(t.c.id == row.id, t.c.lease_token == token)
                                .values(**values)).rowcount == 1

    def _finish(self, row: Any, token: str, error: str | None, now: _dt.datetime) -> str:
        attempts = row.attempts + 1
        if error is None:
            values: dict[str, Any] = {"status": "delivered", "delivered_at": stamp(now),
                                      "last_error": None}
            outcome = "delivered"
        elif attempts >= self.max_attempts:
            values = {"status": "failed", "last_error": error[:2000]}
            outcome = "failed"
        else:
            values = {"status": "pending", "last_error": error[:2000],
                      "next_attempt_at": stamp(now + backoff(attempts))}
            outcome = "retrying"
        if not self._leased(row, token, {**values, "lease_token": None}):
            return "superseded"  # the lease ran out and another pass took the row over
        return outcome

    def run_once(self, now: _dt.datetime | None = None) -> dict[str, int]:
        """Deliver every row that is due; return how many were delivered, retried, failed, or
        taken over by another dispatcher after this one's lease ran out."""
        fixed = now
        now = now or now_utc()
        counts = {"delivered": 0, "retrying": 0, "failed": 0, "superseded": 0}
        claimed = self._claim(now)
        for i, (row, token) in enumerate(claimed):
            if self._stop.is_set():  # hand the rest back for the next pass
                for later, later_token in claimed[i:]:
                    self._leased(later, later_token, {"status": "pending", "lease_token": None,
                                                      "attempts": later.attempts,
                                                      "next_attempt_at": stamp(now)})
                break
            current = fixed or now_utc()
            if row.attempts + 1 > self.max_attempts:  # it kept failing, or crashing its sender
                outcome = self._finish(row, token, f"Gave up after {row.attempts} attempts.",
                                       current)
                counts[outcome] += 1
                continue
            # The lease starts when this row's delivery starts, not when the batch was claimed.
            if not self._leased(row, token, {"next_attempt_at": stamp(current + self.lease)}):
                counts["superseded"] += 1
                continue
            channel = self.channels.get(row.channel)
            error = None
            if channel is None:
                error = f"Channel {row.channel!r} is no longer configured."
            else:
                try:
                    notification = Notification.from_dict(json.loads(row.payload))
                    channel.deliver(notification, row.recipient, row.id)
                except Exception as exc:  # recorded on the row and retried
                    error = redact(f"{exc.__class__.__name__}: {exc}")
            outcome = self._finish(row, token, error, fixed or now_utc())
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
        if self._thread is not None:  # the delivery in flight finishes; the rest go back
            self._thread.join(timeout=20)
            self._thread = None
