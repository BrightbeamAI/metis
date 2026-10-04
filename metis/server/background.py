"""Background work for the server: lapsing overdue whispers, queueing review-date notices, and
clearing old notifications.

``sweep`` runs once over every workspace; the ``Sweeper`` runs it on a timer inside the server,
and ``metis server sweep`` runs it from a scheduler such as cron or a Kubernetes CronJob. Each
workspace is swept in its own transaction, and a workspace with nothing due is only read. With
several replicas on PostgreSQL, one sweeps at a time; the others skip that round.
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("metis.server")


def sweep(repo: Any, now: _dt.datetime | None = None, *, retention_days: int | None = None,
          stopping: Callable[[], bool] = lambda: False) -> dict[str, int]:
    """Lapse whispers past their deadline, queue notices for fragments past their review date,
    and clear notifications older than ``retention_days``; return what was done."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    done = {"workspaces": 0, "lapsed_whispers": 0, "review_notices": 0, "pruned_notifications": 0,
            "errors": 0, "skipped": 0}
    with repo.exclusive("sweep") as mine:
        if not mine:  # another replica is sweeping
            done["skipped"] = 1
            return done
        for summary in repo.list():
            if stopping():
                break
            done["workspaces"] += 1
            try:
                if repo.read(summary.id, lambda e: e.overdue_whispers(now)):
                    lapsed = repo.write(summary.id, lambda e: e.lapse_whispers(now))
                    done["lapsed_whispers"] += len(lapsed)
                if repo.notifier is not None:
                    notes = repo.read(summary.id, lambda e: repo.notifier.review_due(e, now))
                    done["review_notices"] += repo.enqueue(notes)
            except Exception:  # one workspace's failure must not stop the others
                done["errors"] += 1
                log.exception("sweeping %s failed", summary.id)
        if retention_days and not stopping():
            from ..notify import prune

            try:
                done["pruned_notifications"] = prune(repo, retention_days=retention_days, now=now)
            except Exception:
                done["errors"] += 1
                log.exception("clearing old notifications failed")
    return done


class Sweeper:
    def __init__(self, repo: Any, *, retention_days: int | None = None) -> None:
        self.repo = repo
        self.retention_days = retention_days
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, interval: float) -> None:
        if self._thread is not None or interval <= 0:
            return

        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    result = sweep(self.repo, retention_days=self.retention_days,
                                   stopping=self._stop.is_set)
                    if any(result[k] for k in ("lapsed_whispers", "review_notices",
                                               "pruned_notifications", "errors")):
                        log.info("sweep: %s", result)
                except Exception:
                    log.exception("sweep failed")

        self._thread = threading.Thread(target=loop, name="metis-sweep", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
