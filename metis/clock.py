"""The clock behind every timestamp Metis writes into a record.

Outside an engine call this is the real UTC wall clock. A deterministic engine
(``MetisEngine(deterministic=True)``) binds its coordinator clock for the duration of each
of its own calls, so demo output, example files, and the evidence chain are byte-stable
across runs. The binding lives in a context variable and is scoped to the call: a
deterministic engine never affects the timestamps of another engine, of another thread, or
of code that runs outside its calls.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import functools
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any, TypeVar

_source: ContextVar[Callable[[], str] | None] = ContextVar("metis_clock_source", default=None)

_F = TypeVar("_F", bound=Callable[..., Any])


def now_iso() -> str:
    """The current timestamp as an ISO-8601 string (bound source, else real UTC)."""
    source = _source.get()
    if source is not None:
        return source()
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def now_dt() -> _dt.datetime:
    """The current time as a timezone-aware datetime (bound source, else real UTC)."""
    parsed = _dt.datetime.fromisoformat(now_iso().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


@contextlib.contextmanager
def use(source: Callable[[], str] | None) -> Iterator[None]:
    """Bind ``source`` as the clock for the enclosed block; ``None`` binds real time."""
    token = _source.set(source)
    try:
        yield
    finally:
        _source.reset(token)


def scoped(method: _F) -> _F:
    """Run a method under its instance's ``clock_source`` (``None`` means real time)."""

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with use(getattr(self, "clock_source", None)):
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]
