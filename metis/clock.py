"""The clock used for every timestamp Metis writes into records.

By default this is the real UTC wall clock. A deterministic engine
(``MetisEngine(deterministic=True)``) binds this module to its coordinator clock so that
domain records (provenance, reviews, promotions, model-assist records) carry reproducible
timestamps, which makes demo output, example files, and the evidence chain byte-stable
across runs. Constructing a non-deterministic engine rebinds the real clock.

The binding is process-global and last-engine-wins, which suits the sequential demos,
scripts, and tests of this reference toolkit.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

_source: Callable[[], str] | None = None


def set_source(source: Callable[[], str] | None) -> None:
    """Bind a timestamp source returning an ISO-8601 string, or ``None`` for real time."""
    global _source
    _source = source


def now_iso() -> str:
    """The current timestamp as an ISO-8601 string (bound source or real UTC)."""
    if _source is not None:
        return _source()
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
