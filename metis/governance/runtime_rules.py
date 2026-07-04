"""Runtime governance rules shared by the Runtime Orchestrator and the retrieval gate."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..retrieval.gate import RetrievalGate


@dataclass
class RuntimeRules:
    escalate_risk_classes: set[str] = field(default_factory=lambda: {"high", "critical"})

    def build_gate(self) -> RetrievalGate:
        return RetrievalGate(escalate_risk_classes=set(self.escalate_risk_classes))
