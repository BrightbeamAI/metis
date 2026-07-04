"""Observe, accept a structured situated work observation.

Inputs may come from a manual form, a CSV row, a JSON event, or a synthetic example. The
observation is recorded as a CHAP artefact of kind ``tacit.capture_observation``. Nothing
here is trusted knowledge; it is raw input to the loop.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..conditions.context import TacitContext


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    text: str
    work_as_imagined: str | None = None
    work_as_done: str | None = None
    context: TacitContext = Field(default_factory=TacitContext)
    source: str = "manual"  # manual | csv | json | synthetic
    raw: dict[str, Any] = Field(default_factory=dict)


def build_observation(
    *,
    observation_id: str,
    text: str | None = None,
    work_as_imagined: str | None = None,
    work_as_done: str | None = None,
    context: TacitContext | None = None,
    source: str = "manual",
    raw: dict[str, Any] | None = None,
) -> Observation:
    if text is None:
        text = work_as_done or work_as_imagined or ""
    return Observation(
        observation_id=observation_id, text=text, work_as_imagined=work_as_imagined,
        work_as_done=work_as_done, context=context or TacitContext(), source=source,
        raw=raw or {})
