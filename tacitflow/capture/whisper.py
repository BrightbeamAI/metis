"""Whisper, generate a low-burden, bounded probe using CHAP's whisper capability.

The question comes from a YAML template (prompts/whispers/), so template constraints and
``do_not_ask`` rules control the final wording. A local model may *draft* a refinement, but
the template is canonical. Whispers are short, contextual, non-accusatory, and never ask a
worker to justify their personal performance.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.ollama_client import OllamaClient
from ..models.prompts import load_whisper_template
from ..models.structured_outputs import AssistPurpose
from ..taxonomy.categories import Category
from ..taxonomy.mapping import whisper_template_for
from .observe import Observation

_GENERIC = {
    "category": "generic_low_burden",
    "primary_whisper": "You did something differently from the written procedure. What cue or reason prompted that?",
    "follow_ups": ["Does this apply only under particular conditions?", "What should the system not infer from this?"],
    "allowed_response_types": ["confirm", "correct", "dismiss", "defer"],
    "operator_burden_level": "low",
    "do_not_ask": ["Do not ask the operator to justify their personal performance."],
}


class WhisperPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    question: str
    follow_ups: list[str] = Field(default_factory=list)
    options: list[dict[str, str]] = Field(default_factory=list)
    operator_burden_level: str = "low"
    do_not_ask: list[str] = Field(default_factory=list)
    model_draft: str | None = None


def build_whisper(
    category: Category | str,
    observation: Observation,
    *,
    model_client: OllamaClient | None = None,
) -> tuple[WhisperPrompt, dict[str, Any] | None]:
    try:
        template = load_whisper_template(whisper_template_for(Category(category)))
    except Exception:
        template = _GENERIC

    options = [{"id": r, "label": r} for r in template.get("allowed_response_types", ["confirm", "correct", "dismiss", "defer"])]
    assist: dict[str, Any] | None = None
    model_draft = None
    if model_client is not None:
        prompt = (f"Draft a single low-burden, non-accusatory whisper question for a {category} "
                  f"tacit cue. Observation: {observation.text}. Return JSON {{question, follow_ups}}.")
        res = model_client.run(AssistPurpose.draft_whisper, prompt)
        model_draft = res.json().get("question")
        assist = {"purpose": AssistPurpose.draft_whisper.value, "prompt": prompt,
                  "output": res.json(), "used_live_model": res.used_live_model}

    prompt_obj = WhisperPrompt(
        category=str(category),
        question=template.get("primary_whisper", _GENERIC["primary_whisper"]),  # template is canonical
        follow_ups=template.get("follow_ups", []),
        options=options,
        operator_burden_level=template.get("operator_burden_level", "low"),
        do_not_ask=template.get("do_not_ask", []),
        model_draft=model_draft)
    return prompt_obj, assist
