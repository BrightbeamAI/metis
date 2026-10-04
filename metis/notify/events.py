"""Notifications: what happened in a workspace, and who should hear about it."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

# Event names, and the people or agents each one is for.
EVENTS: dict[str, str] = {
    "whisper.asked": "a worker has a whisper to answer",
    "whisper.lapsed": "a whisper went unanswered past its deadline",
    "review.requested": "reviewers have a fragment to review",
    "review.approval": "a review gathered an approval and awaits more",
    "review.decided": "a review was decided; the contributing worker and the reviewers hear",
    "escalation.opened": "a retrieval needs a person's decision",
    "escalation.decided": "a person decided an escalated retrieval",
    "fragment.contested": "a fragment was contested",
    "fragment.revoked": "a fragment was withdrawn, retired, or superseded",
    "fragment.review_due": "a fragment in use is past its review date",
    "member.changed": "a member's roles changed",
}

# Events that carry no one's personal content, so group channels may show them.
GROUP_SAFE = frozenset({
    "review.requested", "review.approval", "review.decided", "escalation.opened",
    "escalation.decided", "fragment.contested", "fragment.revoked", "fragment.review_due",
})


def now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def stamp(moment: _dt.datetime) -> str:
    """A UTC timestamp in one fixed format, so stored timestamps compare as text."""
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class Notification:
    event: str
    workspace_id: str
    workspace_name: str
    recipients: list[str]
    subject: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = field(default_factory=lambda: stamp(now_utc()))
    dedupe_key: str | None = None

    def __post_init__(self) -> None:
        if self.event not in EVENTS:
            raise ValueError(f"Unknown notification event: {self.event}")
        self.recipients = list(dict.fromkeys(self.recipients))

    def as_dict(self) -> dict[str, Any]:
        return {"event": self.event,
                "workspace": {"id": self.workspace_id, "name": self.workspace_name},
                "recipients": self.recipients, "subject": self.subject,
                "occurred_at": self.occurred_at}

    @classmethod
    def from_dict(cls, data: dict[str, Any], dedupe_key: str | None = None) -> Notification:
        ws = data.get("workspace") or {}
        return cls(event=data["event"], workspace_id=ws.get("id", ""),
                   workspace_name=ws.get("name", ""), recipients=list(data.get("recipients") or []),
                   subject=dict(data.get("subject") or {}),
                   occurred_at=data.get("occurred_at") or stamp(now_utc()), dedupe_key=dedupe_key)


def summary(n: Notification, *, personal: bool) -> str:
    """One line describing the notification. ``personal`` messages go to one recipient and may
    carry that recipient's own content (a whisper's question); group messages do not."""
    s, ws = n.subject, n.workspace_name or n.workspace_id
    frag = s.get("fragment_id", "a fragment")
    title = f" ({s['title']})" if s.get("title") else ""
    texts = {
        "whisper.asked": (f"A question awaits your answer in {ws}: “{s.get('question', '')}”"
                          if personal else f"A whisper awaits an answer in {ws}."),
        "whisper.lapsed": f"A whisper in {ws} lapsed without an answer; nothing was stored.",
        "review.requested": f"{frag}{title} awaits review in {ws}.",
        "review.approval": (f"{frag}{title} in {ws} has {s.get('approvals', 0)} of "
                            f"{s.get('required', 0)} approvals for {s.get('outcome', 'promotion')}."),
        "review.decided": f"{frag}{title} in {ws}: {s.get('outcome', 'decided')}.",
        "escalation.opened": (f"A retrieval in {ws} needs a person's decision "
                              f"(escalation {s.get('task_id', '')})."),
        "escalation.decided": (f"Escalation {s.get('task_id', '')} in {ws}: "
                               f"{s.get('outcome', 'decided')}."),
        "fragment.contested": f"{frag}{title} in {ws} was contested ({s.get('action', 'challenge')}).",
        "fragment.revoked": f"{frag}{title} in {ws} is {s.get('status', 'revoked')}.",
        "fragment.review_due": f"{frag}{title} in {ws} is past its review date.",
        "member.changed": (f"Your roles in {ws}: {', '.join(s.get('roles') or []) or 'none'}."
                           if personal else f"Member roles changed in {ws}."),
    }
    return texts[n.event]
