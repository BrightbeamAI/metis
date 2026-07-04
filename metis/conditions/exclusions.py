"""Exclusion-condition evaluation.

An exclusion condition is a partial context. If *all* of its fields match the runtime
context, the fragment is excluded from retrieval even when its positive conditions match.
"""
from __future__ import annotations

from typing import Any


def _value_matches(constraint: Any, actual: Any) -> bool:
    if actual is None:
        return False
    if isinstance(constraint, list):
        actual_set = set(actual) if isinstance(actual, list) else {actual}
        return bool(set(constraint) & actual_set)
    if isinstance(actual, list):
        return constraint in actual
    return constraint == actual


def exclusion_applies(exclusion: dict[str, Any], runtime_values: dict[str, Any]) -> bool:
    if not exclusion:
        return False
    return all(_value_matches(v, runtime_values.get(k)) for k, v in exclusion.items())
