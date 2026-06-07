"""control/1.0 profile helpers.

Revocation, supersession, pause and rollback are CHAP control events. TacitFlow maps:
  revoke     -> control.cancel  (+ tacit.revocation_record)
  supersede  -> control.supersede (+ tacit.supersession_record)
Every control operation is privileged and appended to the evidence chain.
"""
from __future__ import annotations

CONTROL_PAUSE = "control.pause"
CONTROL_RESUME = "control.resume"
CONTROL_CANCEL = "control.cancel"
CONTROL_SUPERSEDE = "control.supersede"
CONTROL_SNAPSHOT = "control.snapshot"
CONTROL_ROLLBACK = "control.rollback"
