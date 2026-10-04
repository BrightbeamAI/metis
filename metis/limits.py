"""Size limits on what callers send.

Whatever Metis accepts is recorded on an append-only chain for good, and every later write of
the workspace stores that chain. So every entry point (the HTTP API, remote MCP, and the
connectors) applies the same limits, and no caller can make a workspace permanently slower.
"""
from __future__ import annotations

import json
from typing import Any

MAX_ID = 128            # observation, fragment, whisper, and task ids
MAX_URI = 320           # participant URIs
MAX_NAME = 200          # titles, names, sites, roles, categories
MAX_TEXT = 4000         # work as done, work as imagined, corrections, summaries
MAX_NOTE = 2000         # rationales, reasons, notes, comments
MAX_CONTEXT_VALUE = 256
MAX_CONTEXT_BYTES = 4096
MAX_ITEMS = 32          # entries in a list or mapping


def check_text(field: str, value: str | None, limit: int = MAX_TEXT) -> None:
    """Raise ``ValueError`` when ``value`` is longer than ``limit`` characters."""
    if value is not None and len(value) > limit:
        raise ValueError(f"{field} is {len(value)} characters long; the limit is {limit}.")


def check_context(data: Any, field: str = "context") -> None:
    """Raise ``ValueError`` when a context is larger than the limits allow."""

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            check_text(path, value, MAX_CONTEXT_VALUE)
        elif isinstance(value, (list, tuple)):
            if len(value) > MAX_ITEMS:
                raise ValueError(f"{path} has {len(value)} entries; the limit is {MAX_ITEMS}.")
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")
        elif isinstance(value, dict):
            if len(value) > MAX_ITEMS:
                raise ValueError(f"{path} has {len(value)} entries; the limit is {MAX_ITEMS}.")
            for key, item in value.items():
                check_text(f"{path} key", str(key), MAX_CONTEXT_VALUE)
                walk(item, f"{path}.{key}")

    walk(data, field)
    size = len(json.dumps(data, default=str))
    if size > MAX_CONTEXT_BYTES:
        raise ValueError(f"{field} is {size} bytes as JSON; the limit is {MAX_CONTEXT_BYTES}.")
