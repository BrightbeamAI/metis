"""Recording a worker's answer that arrives through a chat tool (Slack or Microsoft Teams).

The chat tool has signed the worker in; Metis maps their verified email to a participant, and
records the answer only when that participant is the worker the whisper asked.
"""
from __future__ import annotations

from typing import Any

from ..governance.membership import Role

RESPONSES = ("confirm", "correct", "defer", "dismiss")
LABELS = {"confirm": "That's right", "correct": "Correct it", "defer": "Later",
          "dismiss": "Not relevant"}
CONSENT_TEXT = "I agree that my account is kept and reviewed. I can withdraw it at any time."
# The same consent in the short form chat tools allow for a checkbox (Slack: 75 characters).
CONSENT_SHORT = "Keep my account for review"
CONSENT_NOTE = "I can withdraw it at any time."


def participant_for(email: str | None) -> str | None:
    email = (email or "").strip().lower()
    return f"human:{email}" if "@" in email and " " not in email else None


def record_answer(repo: Any, participant: str, workspace_id: str, whisper_id: str, response: str,
                  consent: bool, corrected_text: str | None = None) -> str:
    """Record the answer; return a sentence to show the worker."""
    from ..limits import MAX_TEXT, check_text

    if not all(isinstance(v, str) and v for v in (workspace_id, whisper_id)):
        raise ValueError("This answer is not one Metis sent.")
    if response not in RESPONSES:
        raise ValueError(f"Unknown answer {response!r}.")
    check_text("Your correction", corrected_text, MAX_TEXT)
    if response in ("confirm", "correct") and not consent:
        raise PermissionError("Tick the consent box to keep your account, or choose Not relevant.")
    if response == "correct" and not (corrected_text or "").strip():
        raise ValueError("Describe it in your own words to correct it.")

    from ..server.operations import answer_draft

    draft = answer_draft(repo, workspace_id, whisper_id, participant, response,
                         corrected_text if response == "correct" else None)

    def answer(engine: Any) -> bool:
        pending = engine.pending_captures.get(whisper_id)
        if pending is None:
            raise LookupError("This question was answered already, or it has closed.")
        if pending.worker != participant:
            raise PermissionError("This question is for someone else.")
        if Role.worker not in engine.roles_of(participant):
            raise PermissionError("You are no longer a worker in this workspace.")
        result = engine.answer_whisper(
            whisper_id, response=response, answered_by=participant,
            corrected_content=corrected_text if response == "correct" else None,
            consent_granted=consent, confirmation_draft=draft)
        return result.fragment is not None

    stored = repo.write(workspace_id, answer)
    if stored:
        return "Thank you. Your account is kept for review, and you can withdraw it at any time."
    return "Thank you. Your answer is recorded; nothing was kept."
