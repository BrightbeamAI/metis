"""Shared fixtures. Everything runs locally and deterministically; no live Ollama needed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tacitflow.conditions.context import TacitContext  # noqa: E402
from tacitflow.consent.model import ConsentRecord, ConsentStatus  # noqa: E402
from tacitflow.engine import TacitFlowEngine  # noqa: E402
from tacitflow.fragment.model import EvidenceStrength, FragmentEvidence  # noqa: E402
from tacitflow.scenarios import run_manufacturing  # noqa: E402


@pytest.fixture
def engine() -> TacitFlowEngine:
    eng = TacitFlowEngine(deterministic=True, use_live_model=False)
    eng.join_default_participants()
    return eng


@pytest.fixture
def granted_consent() -> ConsentRecord:
    return ConsentRecord(consent_status=ConsentStatus.granted)


@pytest.fixture
def match_context() -> TacitContext:
    return TacitContext(site="plant_a", area="utilities", line="line_3",
                        equipment_family="centrifugal_pump", equipment_id="PUMP-A",
                        operating_mode="high_load", shift_pattern="night",
                        trigger_context="pre_alarm", risk_class="moderate", role="operator")


@pytest.fixture
def nonmatch_context() -> TacitContext:
    return TacitContext(site="plant_a", equipment_family="gear_pump",
                        operating_mode="low_load", risk_class="moderate", role="operator")


@pytest.fixture
def captured_fragment(engine, granted_consent, match_context):
    """An Evidence-layer fragment produced by the capture loop."""
    res = engine.capture_observation(
        dict(observation_id="OBS-T1",
             work_as_imagined="Reduce load only when the alarm threshold is crossed.",
             work_as_done="Reduce throughput earlier on low-frequency vibration and a dull acoustic cue.",
             context=match_context, source="synthetic"),
        consent=granted_consent, response="confirm", category="K7_sensory",
        conditions=match_context,
        evidence=FragmentEvidence(recurrence_count=4, evidence_strength=EvidenceStrength.moderate),
        title="Early reduce on dull cue")
    return engine, res


@pytest.fixture
def manufacturing_run():
    return run_manufacturing()
