"""whisper/1.0 profile helpers.

TacitFlow uses CHAP's whisper capability for low-burden, bounded operator probes.
It does NOT define its own whisper mechanism. ``whisper.ask`` / ``whisper.answer`` are
emitted by :class:`tacitflow.integrations.chap.adapter.CHAPAdapter`; this module documents
the param shape and the closed answer set TacitFlow relies on.
"""
from __future__ import annotations

from typing import Any

WHISPER_ASK = "whisper.ask"
WHISPER_ANSWER = "whisper.answer"

# TacitFlow operator responses map onto a closed option set (Tier-1, descriptive only).
RESPONSE_OPTIONS = [
    {"id": "confirm", "label": "Yes, that is what I meant / did"},
    {"id": "correct", "label": "Close, but let me correct it"},
    {"id": "dismiss", "label": "No, that is not right"},
    {"id": "defer", "label": "Ask me later"},
]


def ask_params(*, workspace: str, sender: str, to: str, task_id: str, question: str,
               options: list[dict[str, str]], deadline_ms: int, default_if_lapsed: str,
               urgency: str, ts: str) -> dict[str, Any]:
    return {
        "workspace": workspace, "from": sender, "to": to, "task_id": task_id,
        "question": question, "options": options, "deadline_ms": deadline_ms,
        "default_if_lapsed": default_if_lapsed, "urgency": urgency, "ts": ts,
    }
