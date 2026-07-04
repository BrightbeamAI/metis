"""Local Ollama client for bounded, assistive model calls (default model: Gemma).

Design rules:
  * Local only. Talks to ``config.url`` (default http://localhost:11434). Never a cloud API.
  * Fails gracefully. If Ollama is not running, returns a deterministic fallback rather
    than raising, so the demo and tests run without a live server.
  * Deterministic for CI. With ``deterministic=True`` (the test/demo default) no network call
    is made and outputs are reproducible.
  * Advisory only. Output is always a draft suggestion; it never decides governance.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .model_config import ModelConfig
from .structured_outputs import AssistPurpose

_CATEGORY_KEYWORDS = [
    (("sound", "hear", "heard", "acoustic", "vibration", "smell", "noise", "hum"), "K7_sensory"),
    (("looks", "look ", "appearance", "visual", "colour", "color", "off"), "K8_aesthetic"),
    (("pause", "wait", "waited", "timing", "tempo", "cadence", "rhythm", "earlier"), "K3_rhythmic"),
    (("rule of thumb", "threshold", "exceed", "heuristic"), "K9_heuristic"),
    (("diagnose", "fault", "root cause", "troubleshoot"), "K10_diagnostic"),
    (("before", "anticipate", "predict", "about to"), "K11_anticipatory"),
    (("handover", "handoff", "coordinate", "shift change"), "K14_collaborative"),
    (("escalate", "unsure", "limit", "ask for help"), "K12_metacognitive"),
    (("material", "lot", "batch", "feedstock"), "K5_material"),
    (("machine", "equipment", "pump", "asset"), "K4_equipment_specific"),
]


@dataclass
class ModelRunResult:
    text: str
    used_live_model: bool
    purpose: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None
    fallback: bool = False

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except Exception:
            return {"raw_text": self.text}


def _guess_category(text: str) -> str:
    low = text.lower()
    for keywords, category in _CATEGORY_KEYWORDS:
        if any(k in low for k in keywords):
            return category
    return "K7_sensory"


class OllamaClient:
    def __init__(
        self,
        config: ModelConfig | None = None,
        *,
        deterministic: bool = True,
        responder: Callable[[str, str], str] | None = None,
        http_client: Any = None,
    ) -> None:
        self.config = config or ModelConfig()
        self.deterministic = deterministic
        self._responder = responder
        self._http = http_client

    # ---- availability ----------------------------------------------------------
    def available(self) -> bool:
        if self.deterministic or not self.config.enabled:
            return False
        return self._tags() is not None

    def _tags(self) -> list[str] | None:
        try:
            import httpx

            client = self._http or httpx
            resp = client.get(f"{self.config.url}/api/tags", timeout=2.0)
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return None

    def model_available(self, name: str | None = None) -> bool:
        name = name or self.config.name
        tags = self._tags()
        if tags is None:
            return False
        return any(t == name or t.startswith(name + ":") for t in tags)

    # ---- generation ------------------------------------------------------------
    def run(self, purpose: AssistPurpose | str, prompt: str, *, system: str | None = None,
            fmt: str = "json") -> ModelRunResult:
        purpose_val = purpose.value if isinstance(purpose, AssistPurpose) else str(purpose)
        if self._responder is not None:
            text = self._responder(purpose_val, prompt)
            return ModelRunResult(text=text, used_live_model=False, purpose=purpose_val)
        if self.deterministic or not self.config.enabled or not self.available():
            return self._fallback(purpose_val, prompt)
        return self._generate(purpose_val, prompt, system=system, fmt=fmt)

    def _generate(self, purpose: str, prompt: str, *, system: str | None, fmt: str) -> ModelRunResult:
        try:
            import httpx

            client = self._http or httpx
            payload: dict[str, Any] = {"model": self.config.name, "prompt": prompt, "stream": False}
            if system:
                payload["system"] = system
            if fmt == "json":
                payload["format"] = "json"
            resp = client.post(f"{self.config.url}/api/generate", json=payload, timeout=self.config.timeout_s)
            data = resp.json()
            return ModelRunResult(text=data.get("response", ""), used_live_model=True, purpose=purpose, raw=data)
        except Exception as exc:  # graceful degradation
            res = self._fallback(purpose, prompt)
            res.error = f"ollama unavailable: {exc}"
            return res

    # ---- deterministic fallback (no server) ------------------------------------
    def _fallback(self, purpose: str, prompt: str) -> ModelRunResult:
        excerpt = " ".join(prompt.split())[:240]
        if purpose == AssistPurpose.classify_fragment.value:
            out = {"category": _guess_category(prompt), "rationale": "deterministic-fixture", "alternatives": []}
        elif purpose == AssistPurpose.structure_candidate.value:
            out = {"title": "Candidate fragment (draft)", "content": excerpt,
                   "category": _guess_category(prompt), "suggested_conditions": {}}
        elif purpose == AssistPurpose.draft_whisper.value:
            out = {"question": "You acted differently from the written procedure. What cue prompted that?",
                   "follow_ups": ["Does this apply only under specific conditions?"]}
        elif purpose == AssistPurpose.summarise_confirmation.value:
            out = {"summary": "Operator confirmed the described practice. " + excerpt}
        elif purpose == AssistPurpose.suggest_conditions.value:
            out = {"conditions": {}, "exclusions": []}
        elif purpose == AssistPurpose.review_summary.value:
            out = {"summary": "Draft review summary for Mission Group consideration. " + excerpt,
                   "risks_noted": []}
        elif purpose == AssistPurpose.advisory_wording.value:
            out = {"advisory_text": "Advisory cue (present to a human operator, do not automate).",
                   "use_constraints": ["Present as advisory only.", "Escalate if risk class is high."]}
        else:
            out = {"raw_text": excerpt}
        return ModelRunResult(text=json.dumps(out), used_live_model=False, purpose=purpose, fallback=True)
