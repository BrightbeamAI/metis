"""FastAPI dependencies: the signed-in principal and the workspace repository."""
from __future__ import annotations

from typing import Any

from fastapi import Request

from ..identity import Principal


def principal(request: Request) -> Principal:
    """The caller, from their credentials. ``AuthenticationError`` becomes a 401."""
    return request.app.state.auth.authenticate(request.headers)


def repository(request: Request) -> Any:
    return request.app.state.repo


def settings(request: Request) -> Any:
    return request.app.state.settings


class NotFound(LookupError):
    """The thing asked for does not exist, or the caller may not know that it does."""
