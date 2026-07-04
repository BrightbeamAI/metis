"""Infer, compare work-as-imagined with work-as-done and form a *candidate hypothesis*.

Deterministic rules come first. A local model may help classify or structure the candidate,
but the result is only ever a hypothesis (``tacit.inference_candidate``); never trusted
knowledge. The gap between work-as-imagined and work-as-done is diagnostic, not proof.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.ollama_client import OllamaClient
from ..models.structured_outputs import AssistPurpose
from .observe import Observation


class InferenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    observation_id: str
    hypothesis: str
    category: str
    gap_summary: str
    conditions: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.3
    is_hypothesis: bool = True


def infer_candidate(
    observation: Observation,
    *,
    candidate_id: str,
    model_client: OllamaClient | None = None,
    category: str | None = None,
) -> tuple[InferenceCandidate, dict[str, Any] | None]:
    wai, wad = observation.work_as_imagined, observation.work_as_done
    if wai and wad and wai.strip() != wad.strip():
        gap = f"Work-as-imagined ('{wai}') diverges from work-as-done ('{wad}')."
        hypothesis = f"Under the stated conditions, practitioners do: {wad} (rather than: {wai})."
    else:
        gap = "No explicit work-as-imagined/work-as-done divergence supplied."
        hypothesis = observation.text

    assist: dict[str, Any] | None = None
    if category is None and model_client is not None:
        prompt = (
            "Classify the following situated work observation into one K1-K17 tacit category. "
            "Return JSON {category, rationale}. Observation: " + observation.text)
        res = model_client.run(AssistPurpose.classify_fragment, prompt)
        category = res.json().get("category")
        assist = {"purpose": AssistPurpose.classify_fragment.value, "prompt": prompt,
                  "output": res.json(), "used_live_model": res.used_live_model}
    if category is None:
        # deterministic fallback classification (no model)
        from ..models.ollama_client import _guess_category
        category = _guess_category(observation.text)

    candidate = InferenceCandidate(
        candidate_id=candidate_id, observation_id=observation.observation_id,
        hypothesis=hypothesis, category=category, gap_summary=gap,
        conditions=observation.context.model_dump(mode="json", exclude_none=True))
    return candidate, assist
