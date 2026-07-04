"""MetisEngine, the public façade that wires the toolkit together over one CHAP adapter.

Metis domain model first, tacit memory second, local AI assistance third, CHAP
integration underneath. The engine is what the CLI, the demo, the API, and the examples all
use, so orchestration lives in exactly one place.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .capture.loop import CaptureLoop, CaptureResult
from .conditions.context import TacitContext
from .consent.model import ConsentRecord
from .fragment.store import FragmentStore
from .governance.lifecycle import Governance
from .governance.policy import GovernancePolicy
from .integrations.chap.adapter import CHAPAdapter
from .memory.agent_context import AgentMemoryContext
from .memory.broker import MemoryBroker
from .memory.episodic import EpisodicMemoryStore
from .memory.procedural import ProceduralMemoryStore
from .memory.semantic import SemanticMemoryStore
from .memory.tacit import TacitMemoryStore
from .models.model_config import ModelConfig
from .models.ollama_client import OllamaClient
from .retrieval.decision import RetrievalDecision
from .retrieval.gate import RetrievalGate
from .validation.mission_group import MissionGroup


class MetisEngine:
    def __init__(
        self,
        workspace_id: str = "wsp_metis_demo",
        name: str = "Metis Capture Cell",
        *,
        deterministic: bool = True,
        model_config: ModelConfig | None = None,
        use_live_model: bool = False,
        site: str = "plant_a",
        mode: str = "trial",
    ) -> None:
        self.adapter = CHAPAdapter(workspace_id, name, deterministic=deterministic, mode=mode)
        self.fragments = FragmentStore()
        self.tacit_store = TacitMemoryStore()
        self.gate = RetrievalGate()
        self.procedural = ProceduralMemoryStore()
        self.semantic = SemanticMemoryStore()
        self.episodic = EpisodicMemoryStore()

        cfg = model_config or ModelConfig()
        self.model_client = OllamaClient(cfg, deterministic=not use_live_model)

        # Participant URIs (Capture Cell roles mapped onto CHAP participant types).
        self.operator_uri = f"human:operator@{site}"
        self.whisperer_uri = "agent:whisperer#v1"
        self.mission_group_uri = "group:mission-group@metis.local"
        self.agent_uri = "agent:assistant#v1"

        self.mission_group = MissionGroup(self.mission_group_uri)
        self.governance = Governance(
            fragment_store=self.fragments, adapter=self.adapter, tacit_store=self.tacit_store,
            policy=GovernancePolicy(), mission_group=self.mission_group, gate=self.gate)
        self.capture = CaptureLoop(
            adapter=self.adapter, fragment_store=self.fragments, operator_uri=self.operator_uri,
            whisperer_uri=self.whisperer_uri, mission_group_uri=self.mission_group_uri,
            model_client=self.model_client, governance=self.governance)
        self.broker = MemoryBroker(
            procedural=self.procedural, semantic=self.semantic, episodic=self.episodic,
            fragment_store=self.fragments, tacit_store=self.tacit_store, gate=self.gate,
            adapter=self.adapter)

    # ---- setup -----------------------------------------------------------------
    def join_default_participants(self) -> None:
        self.adapter.join(self.operator_uri, "operator", display_name="Operator",
                          capabilities={"kinds": ["tacit.capture", "tacit.confirm"]})
        self.adapter.join(self.whisperer_uri, "whisperer",
                          capabilities={"kinds": ["tacit.infer", "tacit.whisper"]})
        self.adapter.join(self.mission_group_uri, "mission_group",
                          capabilities={"kinds": ["tacit.validate.tier2"]})
        self.adapter.join(self.agent_uri, "agent",
                          capabilities={"kinds": ["tacit.memory.query"]})

    def load_memory(self, *, procedural_dir=None, semantic_dir=None, episodic_jsonl=None) -> None:
        if procedural_dir:
            self.procedural.load_dir(procedural_dir)
        if semantic_dir:
            self.semantic.load_dir(semantic_dir)
        if episodic_jsonl and Path(episodic_jsonl).exists():
            self.episodic.load_jsonl(episodic_jsonl)

    # ---- pass-throughs ---------------------------------------------------------
    def capture_observation(self, observation_input: dict[str, Any], *, consent: ConsentRecord, **kw) -> CaptureResult:
        return self.capture.run(observation_input, consent=consent, **kw)

    def tier2_review(self, fragment_id: str, outcome: str, **kw) -> dict[str, Any]:
        return self.governance.tier2_review(fragment_id, outcome, **kw)

    def retrieve(self, context: TacitContext, *, role: str | None = None, emit: bool = True) -> RetrievalDecision:
        ids = {mo.fragment_id: mo.memory_id for mo in self.tacit_store.all()}
        decision = self.gate.retrieve(self.fragments.all(), context, role=role, memory_ids=ids)
        if emit:
            task_id = self.adapter.create_task("tacit.retrieve", assignee=self.agent_uri,
                                               delegator=self.agent_uri, task_input=context.model_dump(mode="json", exclude_none=True))
            self.adapter.append_artefact("tacit.retrieval_decision", produced_by=self.agent_uri,
                content=decision.model_dump(mode="json"), task=task_id, method="task.route")
        return decision

    def agent_context(self, task_id: str, context: TacitContext, *, role: str | None = None, emit: bool = True) -> AgentMemoryContext:
        return self.broker.query(task_id, context, role=role, emit=emit, requester=self.agent_uri)

    def export_audit(self, path: str) -> int:
        from .audit.export import export_jsonl
        return export_jsonl(self.adapter, path)

    def verify(self):
        return self.adapter.verify()
