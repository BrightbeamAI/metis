"""MetisEngine, the public façade that wires the toolkit together over one CHAP adapter.

Metis domain model first, tacit memory second, local AI assistance third, CHAP
integration underneath. The engine is what the CLI, the demo, the API, and the examples all
use, so orchestration lives in exactly one place.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import clock
from .capture.loop import CaptureLoop, CaptureResult, PendingCapture, WhisperBudget
from .conditions.context import TacitContext
from .consent.model import ConsentRecord, ConsentStatus
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
from .retrieval.escalation import escalation_actions, open_escalation
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
        chap_store: Any = None,
        ledger: Any = None,
        whisper_budget: WhisperBudget | None = None,
    ) -> None:
        self.adapter = CHAPAdapter(workspace_id, name, deterministic=deterministic, mode=mode,
                                   store=chap_store, ledger=ledger)
        self.site = site
        # A deterministic engine stamps its records from the coordinator clock during its
        # own calls only (see metis.clock); a live engine always uses real time.
        self.clock_source = self.adapter.now_iso if deterministic else None
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
        # Who decides when retrieval escalates (out-of-envelope or high-risk situations).
        self.escalation_assignee = self.operator_uri

        # Named human reviewers behind the Mission Group; promotions need a quorum of them.
        self.mission_group_members = [
            "human:quality-lead@metis.local",
            "human:process-engineer@metis.local",
            "human:safety-officer@metis.local",
        ]
        self.mission_group = MissionGroup(self.mission_group_uri, members=self.mission_group_members)
        self.governance = Governance(
            fragment_store=self.fragments, adapter=self.adapter, tacit_store=self.tacit_store,
            policy=GovernancePolicy(require_named_reviewers=not deterministic),
            mission_group=self.mission_group, gate=self.gate,
            clock_source=self.clock_source)
        self.capture = CaptureLoop(
            adapter=self.adapter, fragment_store=self.fragments, operator_uri=self.operator_uri,
            whisperer_uri=self.whisperer_uri, mission_group_uri=self.mission_group_uri,
            model_client=self.model_client, governance=self.governance,
            whisper_budget=whisper_budget or WhisperBudget())
        # Captures waiting for a worker's answer, keyed by whisper id.
        self.pending_captures: dict[str, PendingCapture] = {}
        self.broker = MemoryBroker(
            procedural=self.procedural, semantic=self.semantic, episodic=self.episodic,
            fragment_store=self.fragments, tacit_store=self.tacit_store, gate=self.gate,
            adapter=self.adapter, escalation_assignee=self.escalation_assignee)

    # ---- setup -----------------------------------------------------------------
    @clock.scoped
    def join_default_participants(self) -> None:
        self.adapter.join(self.operator_uri, "operator", display_name="Operator",
                          capabilities={"kinds": ["tacit.capture", "tacit.confirm"]})
        self.adapter.join(self.whisperer_uri, "whisperer",
                          capabilities={"kinds": ["tacit.infer", "tacit.whisper"]})
        self.adapter.join(self.mission_group_uri, "mission_group",
                          capabilities={"kinds": ["tacit.validate.tier2"]})
        for reviewer in self.mission_group_members:
            self.adapter.join(reviewer, "mission_group_reviewer",
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
    @clock.scoped
    def capture_observation(self, observation_input: dict[str, Any], *, consent: ConsentRecord, **kw) -> CaptureResult:
        return self.capture.run(observation_input, consent=consent, **kw)

    @clock.scoped
    def begin_capture(self, observation_input: dict[str, Any], *, consent: ConsentRecord,
                      worker: str | None = None, **kw) -> PendingCapture:
        """Observe, infer, and whisper to ``worker``; the worker answers via ``answer_whisper``."""
        pending = self.capture.begin(observation_input, consent=consent, worker=worker, **kw)
        if not pending.deferred:
            self.pending_captures[pending.whisper_id] = pending
        return pending

    @clock.scoped
    def answer_whisper(self, whisper_id: str, *, response: str, answered_by: str,
                       corrected_content: str | None = None, free_text: str | None = None,
                       consent_granted: bool | None = None) -> CaptureResult:
        """Record a worker's own answer to a pending whisper (Tier-1 confirmation).

        Only the human worker the whisper was addressed to may answer; an agent can never
        confirm on a worker's behalf. ``consent_granted`` records the worker's consent with
        the answer: ``True`` grants it, ``False`` declines it (the answer is recorded and
        nothing is stored), ``None`` keeps the consent given when the capture began.
        """
        from .integrations.chap.participants import type_of

        pending = self.pending_captures.get(whisper_id)
        if pending is None:
            raise KeyError(f"No pending whisper {whisper_id}; it was answered or never asked.")
        if type_of(answered_by) != "human":
            raise PermissionError("Only a human worker can answer a whisper.")
        if consent_granted:
            pending.consent = pending.consent.model_copy(
                update={"consent_status": ConsentStatus.granted})
        result = self.capture.complete(pending, response=response, corrected_content=corrected_content,
                                       free_text=free_text, answered_by=answered_by,
                                       store=consent_granted is not False)
        del self.pending_captures[whisper_id]
        return result

    @clock.scoped
    def tier2_review(self, fragment_id: str, outcome: str, **kw) -> dict[str, Any]:
        return self.governance.tier2_review(fragment_id, outcome, **kw)

    @clock.scoped
    def request_review(self, fragment_id: str, *, by: str | None = None, reason: str = "") -> str:
        """Open a Mission Group review of a fragment (for example, a renewal before its review
        date); return the CHAP task the reviewers decide on."""
        return self.governance.request_review(fragment_id, by=by, reason=reason)

    @clock.scoped
    def retrieve(self, context: TacitContext, *, role: str | None = None, emit: bool = True) -> RetrievalDecision:
        ids = {mo.fragment_id: mo.memory_id for mo in self.tacit_store.all()}
        decision = self.gate.retrieve(self.fragments.all(), context, role=role, memory_ids=ids)
        escalated = [b for b in decision.blocked if b.escalate]
        if emit:
            task_id = self.adapter.create_task("tacit.retrieve", assignee=self.agent_uri,
                                               delegator=self.agent_uri, task_input=context.model_dump(mode="json", exclude_none=True))
            decision.escalation_task_id = open_escalation(
                self.adapter, requester=self.agent_uri, assignee=self.escalation_assignee,
                runtime_context=decision.runtime_context, items=escalated, origin_task=task_id)
        decision.required_human_actions = escalation_actions(escalated, decision.escalation_task_id)
        if emit:
            self.adapter.append_artefact("tacit.retrieval_decision", produced_by=self.agent_uri,
                content=decision.model_dump(mode="json"), task=task_id)
        return decision

    @clock.scoped
    def evaluate(self, fragment, context: TacitContext, *, role: str | None = None):
        """Evaluate one fragment (or fragment id) against a context on this engine's timeline.

        A deterministic engine runs on its coordinator clock, so its fragments' review dates
        are judged on that same clock.
        """
        frag = self.fragments.require(fragment) if isinstance(fragment, str) else fragment
        return self.gate.evaluate(frag, context, role=role)

    @clock.scoped
    def agent_context(self, task_id: str, context: TacitContext, *, role: str | None = None, emit: bool = True) -> AgentMemoryContext:
        return self.broker.query(task_id, context, role=role, emit=emit, requester=self.agent_uri)

    # ---- persistence -------------------------------------------------------------
    def export_state(self) -> dict[str, Any]:
        """The Metis domain state of this workspace (the CHAP chain lives in its own store)."""
        return {
            "version": 1,
            "name": self.adapter.name,
            "site": self.site,
            "workspace": self.adapter.descriptor(),
            "fragments": [f.model_dump(mode="json") for f in self.fragments.all()],
            "memory_objects": [m.model_dump(mode="json") for m in self.tacit_store.all()],
            "procedural": [e.model_dump(mode="json") for e in self.procedural.entries],
            "semantic": [e.model_dump(mode="json") for e in self.semantic.entries],
            "episodic": [e.model_dump(mode="json") for e in self.episodic.entries],
            "counters": {"fragment": self.capture._frag_seq, "assist": self.capture._assist_seq,
                         "memory": self.governance._mem_seq},
            "governance_refs": self.governance.refs,
            "pending_captures": [p.model_dump(mode="json") for p in self.pending_captures.values()],
        }

    def import_state(self, data: dict[str, Any]) -> None:
        """Load domain state written by ``export_state`` into this engine."""
        from .fragment.model import TacitFragment
        from .memory.agent_context import MemoryEntry
        from .memory.tacit import TacitMemoryObject

        for f in data.get("fragments", []):
            self.fragments.put(TacitFragment.model_validate(f))
        for m in data.get("memory_objects", []):
            self.tacit_store.put(TacitMemoryObject.model_validate(m))
        self.procedural.entries = [MemoryEntry.model_validate(e) for e in data.get("procedural", [])]
        self.semantic.entries = [MemoryEntry.model_validate(e) for e in data.get("semantic", [])]
        self.episodic.entries = [MemoryEntry.model_validate(e) for e in data.get("episodic", [])]
        counters = data.get("counters", {})
        self.capture._frag_seq = counters.get("fragment", 0)
        self.capture._assist_seq = counters.get("assist", 0)
        self.governance._mem_seq = counters.get("memory", 0)
        self.governance.refs = dict(data.get("governance_refs", {}))
        for p in data.get("pending_captures", []):
            pending = PendingCapture.model_validate(p)
            self.pending_captures[pending.whisper_id] = pending

    def export_audit(self, path: str) -> int:
        from .audit.export import export_jsonl
        return export_jsonl(self.adapter, path)

    def verify(self):
        return self.adapter.verify()
