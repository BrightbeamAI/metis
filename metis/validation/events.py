"""Validation events (``tacit.validation_event``).

A validation event records something governance-relevant that happened during capture or
review and is itself no decision. ``event`` names it:

- ``whisper_deferred``: the worker's prompt budget was reached, so the whisper waits;
- ``consent_declined``: the worker answered and withheld consent, so nothing was stored;
- ``whisper_lapsed``: the worker did not answer before the whisper's deadline, so nothing was
  stored and the capture closed;
- ``contestability``: a worker or reviewer contested a fragment (the fields of a
  ``ContestabilityRecord`` follow).

The remaining fields depend on the event.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ValidationEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: Literal["whisper_deferred", "consent_declined", "whisper_lapsed", "contestability"]
    worker: str | None = None  # CHAP participant URI of the worker, for capture events
    candidate_id: str | None = None  # the inference candidate a capture event concerns
    fragment_id: str | None = None  # the fragment a contest concerns
