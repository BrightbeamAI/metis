"""FastAPI dependencies: the signed-in principal and the workspace repository."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from ..identity import Principal


def principal(request: Request) -> Principal:
    """The caller, from their credentials. ``AuthenticationError`` becomes a 401."""
    who = request.app.state.auth.authenticate(request.headers)
    request.state.principal = who.uri  # for the request log
    return who


def repository(request: Request, who: Principal = Depends(principal)) -> Any:
    """The repository as the caller sees it: only workspaces they belong or belonged to."""
    from .access import ScopedRepository

    return ScopedRepository(request.app.state.repo, who)


def settings(request: Request) -> Any:
    return request.app.state.settings


class NotFound(LookupError):
    """The thing asked for does not exist, or the caller may not know that it does."""
