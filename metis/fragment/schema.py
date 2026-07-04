"""JSON Schema export for the fragment models."""
from __future__ import annotations

from typing import Any

from ..conditions.context import TacitContext
from ..consent.model import ConsentRecord
from .model import FragmentEvidence, Provenance, TacitFragment


def tacit_fragment_schema() -> dict[str, Any]:
    return TacitFragment.model_json_schema()


def tacit_context_schema() -> dict[str, Any]:
    return TacitContext.model_json_schema()


def provenance_schema() -> dict[str, Any]:
    return Provenance.model_json_schema()


def evidence_schema() -> dict[str, Any]:
    return FragmentEvidence.model_json_schema()


def consent_schema() -> dict[str, Any]:
    return ConsentRecord.model_json_schema()
