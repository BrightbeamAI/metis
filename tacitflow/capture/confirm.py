"""Confirm, capture the operator's Tier-1 response (descriptive fidelity only).

Allowed responses: confirm / correct / dismiss / defer. A local model may summarise the
confirmation, but the original response and the human-confirmed summary are both preserved.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from ..models.ollama_client import OllamaClient
from ..models.structured_outputs import AssistPurpose
from ..validation.tier1 import OperatorResponse
from .whisper import WhisperPrompt


class ConfirmationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: OperatorResponse
    corrected_content: str | None = None
    free_text: str | None = None
    summary: str | None = None


def operator_confirm(
    prompt: WhisperPrompt,
    response: OperatorResponse | str,
    *,
    corrected_content: str | None = None,
    free_text: str | None = None,
    model_client: OllamaClient | None = None,
) -> tuple[ConfirmationResult, dict[str, Any] | None]:
    response = OperatorResponse(response)
    assist: dict[str, Any] | None = None
    summary = None
    if model_client is not None and response in (OperatorResponse.confirm, OperatorResponse.correct):
        basis = corrected_content or free_text or prompt.question
        p = f"Summarise this operator confirmation in one sentence. Return JSON {{summary}}. Text: {basis}"
        res = model_client.run(AssistPurpose.summarise_confirmation, p)
        summary = res.json().get("summary")
        assist = {"purpose": AssistPurpose.summarise_confirmation.value, "prompt": p,
                  "output": res.json(), "used_live_model": res.used_live_model}
    return ConfirmationResult(response=response, corrected_content=corrected_content,
                              free_text=free_text, summary=summary), assist
