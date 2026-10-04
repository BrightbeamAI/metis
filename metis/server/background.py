"""Background work for the server: lapsing overdue whispers and queueing review-date notices.

``sweep`` runs once over every workspace; the ``Sweeper`` runs it on a timer inside the server,
and ``metis server sweep`` runs it from a scheduler such as cron or a Kubernetes CronJob. Each
workspace is swept in its own transaction, and a workspace with nothing due is only read.
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
from typing import Any

log = logging.getLogger("metis.server")


def sweep(repo: Any, now: _dt.datetime | None = None) -> dict[str, int]:
    """Lapse whispers past their deadline and queue notices for fragments past their review
    date; return what was done."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    done = {"workspaces": 0, "lapsed_whispers": 0, "review_notices": 0, "errors": 0}
    for summary in repo.list():
        done["workspaces"] += 1
        try:
            if repo.read(summary.id, lambda e: e.overdue_whispers(now)):
                done["lapsed_whispers"] += len(repo.write(summary.id, lambda e: e.lapse_whispers(now)))
            if repo.notifier is not None:
                notes = repo.read(summary.id, lambda e: repo.notifier.review_due(e, now))
                done["review_notices"] += repo.enqueue(notes)
        except Exception:  # one workspace's failure must not stop the others
            done["errors"] += 1
            log.exception("sweeping %s failed", summary.id)
    return done


class Sweeper:
    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, interval: float) -> None:
        if self._thread is not None or interval <= 0:
            return

        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    result = sweep(self.repo)
                    if result["lapsed_whispers"] or result["review_notices"] or result["errors"]:
                        log.info("sweep: %s", result)
                except Exception:
                    log.exception("sweep failed")

        self._thread = threading.Thread(target=loop, name="metis-sweep", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
