"""Bridges a TacitFragment to its CHAP artefact representation (kind ``tacit.fragment``)."""
from __future__ import annotations

from typing import Any

from .model import TacitFragment

FRAGMENT_KIND = "tacit.fragment"


def fragment_to_content(fragment: TacitFragment) -> dict[str, Any]:
    """The artefact payload for a fragment (JSON-mode dump, enums as values)."""
    return fragment.model_dump(mode="json")
