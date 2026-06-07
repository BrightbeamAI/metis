import pytest

from tacitflow.consent.model import ConsentRecord, ConsentStatus
from tacitflow.fragment.model import EvidenceStrength, FragmentEvidence
from tacitflow.taxonomy.categories import AuthorityLayer, SourcePathway, ValidationState
from tacitflow.validation.states import InvalidTransition, assert_transition, can_transition


def test_legal_and_illegal_transitions():
    assert can_transition(ValidationState.captured, ValidationState.tier1_confirmed)
    assert can_transition(ValidationState.tier2_pending, ValidationState.promoted_to_advisory)
    assert not can_transition(ValidationState.tier1_confirmed, ValidationState.promoted_to_advisory)
    with pytest.raises(InvalidTransition):
        assert_transition(ValidationState.rejected, ValidationState.promoted_to_advisory)


def test_mission_group_promotes_to_advisory(captured_fragment):
    engine, res = captured_fragment
    assert res.fragment.authority_layer == AuthorityLayer.evidence
    out = engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", summary="ok")
    assert res.fragment.authority_layer == AuthorityLayer.advisory
    assert res.fragment.validation_state == ValidationState.promoted_to_advisory
    assert out["memory"].memory_id


def test_endogenous_cannot_self_promote(engine):
    from tacitflow.fragment.model import TacitFragment
    from tacitflow.governance.policy import GovernancePolicy
    from tacitflow.taxonomy.categories import Category
    f = TacitFragment.new(fragment_id="EF-1", title="t", content="c", category=Category.K9_heuristic,
                          source_pathway=SourcePathway.endogenous,
                          consent=ConsentRecord(consent_status=ConsentStatus.granted),
                          evidence=FragmentEvidence(recurrence_count=5, evidence_strength=EvidenceStrength.strong))
    ok, why = GovernancePolicy().can_promote(f, AuthorityLayer.advisory, mission_group_reviewed=False)
    assert not ok and "self-promote" in why


def test_endogenous_needs_higher_bar_even_with_review(engine):
    from tacitflow.fragment.model import TacitFragment
    from tacitflow.governance.policy import GovernancePolicy
    from tacitflow.taxonomy.categories import Category
    weak = TacitFragment.new(fragment_id="EF-2", title="t", content="c", category=Category.K9_heuristic,
                             source_pathway=SourcePathway.endogenous,
                             consent=ConsentRecord(consent_status=ConsentStatus.granted))
    ok, why = GovernancePolicy().can_promote(weak, AuthorityLayer.advisory, mission_group_reviewed=True)
    assert not ok  # recurrence/strength too low


def test_controlled_requires_change_control(captured_fragment):
    engine, res = captured_fragment
    with pytest.raises(PermissionError):
        engine.tier2_review(res.fragment.fragment_id, "promoted_to_controlled", summary="no change control")


def test_rejected_fragment_retained_in_audit(captured_fragment):
    engine, res = captured_fragment
    before = engine.adapter.chain.count
    engine.tier2_review(res.fragment.fragment_id, "rejected", summary="not safe")
    assert res.fragment.validation_state == ValidationState.rejected
    assert engine.adapter.chain.count > before
    kinds = [a["kind"] for a in engine.adapter.artefacts.values()]
    assert "tacit.rejection_record" in kinds
    assert engine.fragments.get(res.fragment.fragment_id) is not None  # not deleted
