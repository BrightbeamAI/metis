"""One writer per workspace, across processes.

A workspace's CHAP coordinator, ledger, and domain store must have a single writer: two
processes that each hold their own copy would overwrite each other's evidence. A process that
opens a workspace for writing takes an exclusive lock on ``<workspace>/.lock`` for as long as
it runs, and the operating system releases it when the process exits, even after a crash.
The lock is re-entrant within one process, so reopening a workspace there is allowed.
Read-only opens do not take the lock.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import IO, Any

_HELD: dict[str, IO[Any]] = {}


class WorkspaceBusy(RuntimeError):
    """Another process has the workspace open for writing."""


def _lock_nonblocking(fh: IO[Any]) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def acquire(path: str | Path) -> None:
    """Take the writer lock at ``path``, or raise ``WorkspaceBusy``."""
    path = Path(path)
    key = str(path.resolve())
    if key in _HELD:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")  # held open for the life of the process
    try:
        _lock_nonblocking(fh)
    except OSError:
        fh.seek(0)
        owner = fh.read().strip()
        fh.close()
        who = f" (pid {owner})" if owner else ""
        raise WorkspaceBusy(
            f"{path.parent.name} is open for writing in another Metis process{who}. "
            "Stop that process, or use another workspace.") from None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    _HELD[key] = fh


def held(path: str | Path) -> bool:
    return str(Path(path).resolve()) in _HELD


def release(path: str | Path) -> None:
    """Give up the writer lock at ``path`` if this process holds it."""
    fh = _HELD.pop(str(Path(path).resolve()), None)
    if fh is not None:
        fh.close()
