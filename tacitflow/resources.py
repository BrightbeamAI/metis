"""Resolve packaged resource directories (prompts, examples, schemas, profiles, templates).

These live at the repository root in the local-first / editable-install layout. Resolution
prefers an explicit env var, then the repo root relative to this file, then the CWD.
"""
from __future__ import annotations

import os
from pathlib import Path

_THIS = Path(__file__).resolve()


def repo_root() -> Path:
    env = os.environ.get("TACITFLOW_REPO")
    if env:
        return Path(env)
    # tacitflow/resources.py -> tacitflow/ -> repo root
    candidate = _THIS.parents[1]
    if (candidate / "examples").exists() or (candidate / "prompts").exists():
        return candidate
    return Path.cwd()


def _dir(name: str) -> Path:
    return repo_root() / name


def prompts_dir() -> Path:
    return _dir("prompts")


def examples_dir() -> Path:
    return _dir("examples")


def schemas_dir() -> Path:
    return _dir("schemas")


def profiles_dir() -> Path:
    return _dir("profiles")


def templates_dir() -> Path:
    return _dir("templates")
