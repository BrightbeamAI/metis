"""Deterministic condition matching for the retrieval gate.

This is the opposite of semantic similarity: a fragment is eligible only when its
structured conditions are satisfied by the runtime context. Matching fails *closed*, an
unknown runtime value never counts as a match.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from .context import CONTEXT_KEYS, TacitContext
from .exclusions import _value_matches, exclusion_applies


@dataclass
class MatchResult:
    ok: bool
    unmatched: list[str] = field(default_factory=list)
    excluded_by: dict[str, Any] | None = None
    out_of_window: bool = False
    detail: str = ""


def _runtime_values(context: TacitContext) -> dict[str, Any]:
    values = {k: getattr(context, k) for k in CONTEXT_KEYS}
    values.update(context.environmental_conditions)
    return values


def match(conditions: TacitContext, context: TacitContext,
          now: _dt.datetime | None = None) -> MatchResult:
    """Return whether ``conditions`` are satisfied by the runtime ``context``."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)

    # Validity window.
    if conditions.valid_from and now < _as_utc(conditions.valid_from):
        return MatchResult(ok=False, out_of_window=True, detail="not yet valid")
    if conditions.valid_until and now > _as_utc(conditions.valid_until):
        return MatchResult(ok=False, out_of_window=True, detail="validity window elapsed")

    runtime = _runtime_values(context)

    unmatched: list[str] = []
    for key in CONTEXT_KEYS:
        constraint = getattr(conditions, key)
        if constraint is None:
            continue
        if not _value_matches(constraint, runtime.get(key)):
            unmatched.append(key)
    for key, constraint in conditions.environmental_conditions.items():
        if not _value_matches(constraint, runtime.get(key)):
            unmatched.append(f"env:{key}")

    if unmatched:
        return MatchResult(ok=False, unmatched=unmatched, detail="conditions do not match")

    # Exclusions are checked against the runtime context.
    for exclusion in conditions.exclusion_conditions:
        if exclusion_applies(exclusion, runtime):
            return MatchResult(ok=False, excluded_by=exclusion, detail="exclusion condition applies")

    return MatchResult(ok=True, detail="all conditions satisfied")


def _as_utc(dt: _dt.datetime) -> _dt.datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)
