"""handoff/1.0 profile helpers.

Shift and responsibility transfer use CHAP's handoff capability
(``handoff.propose`` / ``handoff.accept`` / ``handoff.decline``).
"""
from __future__ import annotations

HANDOFF_PROPOSE = "handoff.propose"
HANDOFF_ACCEPT = "handoff.accept"
HANDOFF_DECLINE = "handoff.decline"
