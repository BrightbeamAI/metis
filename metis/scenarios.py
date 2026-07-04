"""Canonical synthetic scenarios, shared by the demo, CLI, API, and tests.

Each scenario runs entirely locally and deterministically. The manufacturing pump-vibration
scenario is the primary end-to-end walkthrough; batch quality and shift handover follow the
same shape so every example is a full, runnable demo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .conditions.context import TacitContext
from .consent.model import AttributionMode, ConsentRecord, ConsentStatus, Visibility
from .engine import MetisEngine
from .fragment.model import EvidenceStrength, FragmentEvidence
from .memory.agent_context import AgentMemoryContext
from .retrieval.decision import RetrievalDecision


@dataclass
class ScenarioSpec:
    key: str
    workspace_id: str
    name: str
    site: str
    categories: list[str]
    observation: dict[str, Any]
    conditions: dict[str, Any]
    match_context: dict[str, Any]
    nonmatch_context: dict[str, Any]
    category: str
    title: str
    corrected_content: str
    use_constraints: list[str]
    evidence: dict[str, Any]
    review_dimensions: dict[str, str]
    review_summary: str
    procedural: list[tuple[str, str]]
    semantic: list[tuple[str, str, dict[str, Any]]]
    episodic: list[tuple[str, str, dict[str, Any]]]
    linked_procedural: list[str] = field(default_factory=list)
    linked_semantic: list[str] = field(default_factory=list)
    linked_episodic: list[str] = field(default_factory=list)


@dataclass
class DemoRun:
    engine: MetisEngine
    spec: ScenarioSpec | None = None
    steps: list[tuple[str, str]] = field(default_factory=list)
    fragment: Any = None
    memory: Any = None
    match_decision: RetrievalDecision | None = None
    nonmatch_decision: RetrievalDecision | None = None
    agent_context: AgentMemoryContext | None = None


def _granted_consent() -> ConsentRecord:
    return ConsentRecord(
        consent_required=True, consent_status=ConsentStatus.granted,
        attribution_mode=AttributionMode.role, visibility=Visibility.agent_visible,
        withdrawal_allowed=True, worker_visible_record=True)


def run_spec(spec: ScenarioSpec, engine: MetisEngine | None = None, *,
             use_live_model: bool = False) -> DemoRun:
    engine = engine or MetisEngine(workspace_id=spec.workspace_id, name=spec.name,
                                       deterministic=True, use_live_model=use_live_model,
                                       site=spec.site)
    run = DemoRun(engine=engine, spec=spec)

    def s(label: str, detail: str) -> None:
        run.steps.append((label, detail))

    s("1. Metis workspace created.", engine.adapter.workspace_id)
    engine.join_default_participants()
    s("2. Participants added.", ", ".join(engine.adapter.participants.keys()))

    for source, content in spec.procedural:
        engine.procedural.add(source, content)
    s("3. Procedural memory loaded.", ", ".join(p[0] for p in spec.procedural))
    for source, content, meta in spec.semantic:
        engine.semantic.add(source, content, **meta)
    s("4. Semantic memory loaded.", ", ".join(p[0] for p in spec.semantic))
    for source, content, meta in spec.episodic:
        engine.episodic.add(source, content, **meta)
    s("5. Episodic memory loaded.", ", ".join(p[0] for p in spec.episodic))

    model_state = "live Gemma model" if engine.model_client.available() else "deterministic fixtures"
    s("6. Local model status checked.", f"using {model_state}")

    cond = TacitContext(**spec.conditions)
    s("7. Observation loaded.", f"{spec.observation['observation_id']} (work-as-imagined vs work-as-done gap)")

    result = engine.capture_observation(
        dict(observation_id=spec.observation["observation_id"],
             work_as_imagined=spec.observation["work_as_imagined"],
             work_as_done=spec.observation["work_as_done"],
             context=cond, source="synthetic"),
        consent=_granted_consent(), response="confirm",
        corrected_content=spec.corrected_content, title=spec.title, conditions=cond,
        evidence=FragmentEvidence(**spec.evidence), category=spec.category, use_model=True)
    run.fragment = result.fragment
    s("8. Candidate fragment inferred.", f"{result.candidate.candidate_id} [{result.candidate.category}] (hypothesis only)")
    assist_kind = "Gemma (live)" if result.used_live_model else "deterministic fixtures"
    s("9. Local AI assistance.", f"{len(result.model_assist_records)} model-assist records via {assist_kind}")
    s("10. Whisper generated (CHAP whisper).", result.whisper.question)
    s("11. Operator confirmation recorded.", f"response={result.confirmation.response.value}")
    result.fragment.use_constraints = list(spec.use_constraints)
    s("12. Evidence-layer fragment stored.", f"{result.fragment.fragment_id} [{result.fragment.authority_layer.value}]")

    out = engine.tier2_review(
        result.fragment.fragment_id, "promoted_to_advisory",
        dimension_assessments=spec.review_dimensions, summary=spec.review_summary,
        linked_procedural_refs=spec.linked_procedural, linked_semantic_refs=spec.linked_semantic,
        linked_episodic_refs=spec.linked_episodic)
    run.memory = out["memory"]
    s("13. Mission Group review recorded.", "Tier-2 decision: promoted_to_advisory")
    s("14. Fragment promoted to Advisory layer.", result.fragment.authority_layer.value)
    s("15. Tacit memory object created.", run.memory.memory_id)

    match_ctx = TacitContext(**spec.match_context)
    nomatch_ctx = TacitContext(**spec.nonmatch_context)
    run.match_decision = engine.retrieve(match_ctx)
    s("16. Retrieval allowed under matching context.", f"{len(run.match_decision.eligible)} eligible")
    run.nonmatch_decision = engine.retrieve(nomatch_ctx)
    reason = run.nonmatch_decision.blocked[0].reason if run.nonmatch_decision.blocked else "n/a"
    s("17. Retrieval blocked under non-matching context.", f"reason={reason}")

    run.agent_context = engine.agent_context(f"tsk_runtime_{spec.key}", match_ctx)
    s("18. Agent memory context generated.",
      f"procedural={len(run.agent_context.procedural_memory)} semantic={len(run.agent_context.semantic_memory)} "
      f"episodic={len(run.agent_context.episodic_memory)} tacit={len(run.agent_context.tacit_memory)}")
    s("19. Audit chain ready for export.", f"{engine.adapter.chain.count} evidence entries")
    return run


MANUFACTURING = ScenarioSpec(
    key="manufacturing-pump-vibration",
    workspace_id="wsp_pump_vibration", name="Pump Vibration Capture Cell", site="plant_a",
    categories=["K7_sensory", "K10_diagnostic", "K4_equipment_specific"],
    observation={
        "observation_id": "OBS-1",
        "work_as_imagined": "Reduce load only when the alarm threshold is crossed.",
        "work_as_done": ("Reduce throughput earlier when high-load operation coincides with "
                         "low-frequency vibration and a dull acoustic cue.")},
    conditions=dict(site="plant_a", area="utilities", line="line_3",
                    equipment_family="centrifugal_pump", equipment_id="PUMP-A",
                    operating_mode="high_load", shift_pattern="night",
                    trigger_context="pre_alarm", exclusion_conditions=[{"operating_mode": "startup"}]),
    match_context=dict(site="plant_a", area="utilities", line="line_3",
                       equipment_family="centrifugal_pump", equipment_id="PUMP-A",
                       operating_mode="high_load", shift_pattern="night",
                       trigger_context="pre_alarm", risk_class="moderate", role="operator"),
    nonmatch_context=dict(site="plant_a", equipment_family="gear_pump",
                          operating_mode="low_load", risk_class="moderate", role="operator"),
    category="K7_sensory",
    title="Early throughput reduction on dull acoustic cue",
    corrected_content=("Experienced operators reduce throughput earlier when high-load operation "
                       "coincides with low-frequency vibration and a dull acoustic cue."),
    use_constraints=[
        "Present as an advisory cue only.",
        "Do not automatically reduce throughput.",
        "Ask the human operator to confirm the acoustic cue.",
        "Escalate if risk class is high."],
    evidence=dict(recurrence_count=4, evidence_strength=EvidenceStrength.moderate,
                  supporting_cases=["case-1"], comparison_baseline="SOP-17",
                  outcome_link="avoided 3 alarm events"),
    review_dimensions={"description_fidelity": "faithful", "operational_relevance": "high",
                       "normative_alignment": "acceptable", "safety_risk": "low",
                       "evidence_strength": "moderate", "consent_status": "granted"},
    review_summary="Recurs across 4 cases; promote to Advisory as a conditional cue, not a rule.",
    procedural=[("SOP-17", "Reduce load only when the alarm threshold X is crossed.")],
    semantic=[("equipment_metadata", "Pump A is a centrifugal pump on Line 3.",
               dict(equipment_family="centrifugal_pump", equipment_id="PUMP-A")),
              ("vibration_concepts", "Low-frequency vibration can precede bearing distress.",
               dict(equipment_family="centrifugal_pump"))],
    episodic=[("case-1", "Three similar cases led to alarm events within 20 minutes.",
               dict(equipment_family="centrifugal_pump"))],
    linked_procedural=["SOP-17"], linked_semantic=["equipment_metadata"], linked_episodic=["case-1"])


BATCH_QUALITY = ScenarioSpec(
    key="batch-quality-visual-inspection",
    workspace_id="wsp_batch_quality", name="Batch Quality Capture Cell", site="plant_b",
    categories=["K7_sensory", "K8_aesthetic"],
    observation={
        "observation_id": "OBS-BQ-1",
        "work_as_imagined": "Pass the batch unless the lab measure flags drift.",
        "work_as_done": "Flag the batch as 'looks off' before the lab measure confirms drift."},
    conditions=dict(site="plant_b", area="finishing", product_family="resin_batch",
                    operating_mode="inspection", trigger_context="pre_lab_result"),
    match_context=dict(site="plant_b", area="finishing", product_family="resin_batch",
                       operating_mode="inspection", trigger_context="pre_lab_result",
                       risk_class="moderate", role="quality_specialist"),
    nonmatch_context=dict(site="plant_b", product_family="film_batch",
                          operating_mode="production", risk_class="moderate"),
    category="K8_aesthetic",
    title="Visual 'looks off' precedes lab-confirmed drift",
    corrected_content=("A quality specialist flags a resin batch as 'looks off' before the lab "
                       "measure confirms drift, based on surface sheen against annotated exemplars."),
    use_constraints=[
        "Present as an advisory cue requiring exemplar comparison.",
        "Do not convert into a universal rule.",
        "Ask a human to confirm against annotated exemplars before action.",
        "Escalate if risk class is high."],
    evidence=dict(recurrence_count=2, evidence_strength=EvidenceStrength.weak,
                  uncertainty="Subjective visual judgement; weak evidence so far.",
                  counterexamples=["A glossy batch once passed the lab measure cleanly."]),
    review_dimensions={"description_fidelity": "faithful", "operational_relevance": "medium",
                       "normative_alignment": "acceptable", "quality_risk": "medium",
                       "evidence_strength": "weak", "consent_status": "granted"},
    review_summary="Promote as advisory context only; weak evidence, requires exemplar review.",
    procedural=[("QA-04", "Release a batch unless a lab measure flags drift beyond tolerance.")],
    semantic=[("resin_metadata", "Resin batches are graded on surface sheen and clarity.",
               dict(product_family="resin_batch"))],
    episodic=[("bq-case-1", "Two 'looks off' calls later matched lab-confirmed drift.",
               dict(product_family="resin_batch"))],
    linked_procedural=["QA-04"], linked_semantic=["resin_metadata"], linked_episodic=["bq-case-1"])


SHIFT_HANDOVER = ScenarioSpec(
    key="shift-handover-gap",
    workspace_id="wsp_shift_handover", name="Shift Handover Capture Cell", site="plant_a",
    categories=["K14_collaborative", "K12_metacognitive"],
    observation={
        "observation_id": "OBS-SH-1",
        "work_as_imagined": "A completed handover form means the handover is complete.",
        "work_as_done": "The team lead senses the handover is incomplete even though the form is filled."},
    conditions=dict(site="plant_a", area="control_room", operating_mode="handover",
                    shift_pattern="night_to_day", trigger_context="incomplete_handover"),
    match_context=dict(site="plant_a", area="control_room", operating_mode="handover",
                       shift_pattern="night_to_day", trigger_context="incomplete_handover",
                       risk_class="moderate", role="team_lead"),
    nonmatch_context=dict(site="plant_a", area="warehouse", operating_mode="routine",
                          risk_class="moderate"),
    category="K14_collaborative",
    title="Felt-incomplete handover despite a complete form",
    corrected_content=("Team leads sense an incomplete handover when open threads are ticked off on "
                       "the form but not confirmed verbally between outgoing and incoming shifts."),
    use_constraints=[
        "Present as a handover checklist prompt, not automation.",
        "Ask the incoming lead to confirm open threads verbally.",
        "Do not auto-close the handover.",
        "Escalate if risk class is high."],
    evidence=dict(recurrence_count=3, evidence_strength=EvidenceStrength.moderate,
                  outcome_link="reduced repeat incidents across shift boundaries"),
    review_dimensions={"description_fidelity": "faithful", "operational_relevance": "high",
                       "normative_alignment": "acceptable", "safety_risk": "medium",
                       "evidence_strength": "moderate", "consent_status": "granted"},
    review_summary="Promote as advisory checklist guidance for handovers, not automation.",
    procedural=[("HANDOVER-SOP", "Complete the handover form and tick all open items before sign-off.")],
    semantic=[("shift_metadata", "Night-to-day handovers cover three control-room desks.",
               dict(area="control_room"))],
    episodic=[("sh-case-1", "A filled form still missed an open valve-isolation thread; caught verbally.",
               dict(area="control_room"))],
    linked_procedural=["HANDOVER-SOP"], linked_semantic=["shift_metadata"], linked_episodic=["sh-case-1"])


SPECS = {s.key: s for s in (MANUFACTURING, BATCH_QUALITY, SHIFT_HANDOVER)}


def run_manufacturing(engine: MetisEngine | None = None, *, use_live_model: bool = False) -> DemoRun:
    return run_spec(MANUFACTURING, engine, use_live_model=use_live_model)


def run_batch_quality(engine: MetisEngine | None = None, *, use_live_model: bool = False) -> DemoRun:
    return run_spec(BATCH_QUALITY, engine, use_live_model=use_live_model)


def run_shift_handover(engine: MetisEngine | None = None, *, use_live_model: bool = False) -> DemoRun:
    return run_spec(SHIFT_HANDOVER, engine, use_live_model=use_live_model)


SCENARIOS = {
    "manufacturing-pump-vibration": run_manufacturing,
    "batch-quality-visual-inspection": run_batch_quality,
    "shift-handover-gap": run_shift_handover,
}
