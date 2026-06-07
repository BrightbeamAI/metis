import datetime as dt

from tacitflow.conditions.context import TacitContext
from tacitflow.consent.model import ConsentRecord, ConsentStatus
from tacitflow.fragment.model import TacitFragment
from tacitflow.retrieval.blocked_reasons import BlockedReason
from tacitflow.retrieval.gate import RetrievalGate
from tacitflow.taxonomy.categories import (
    AuthorityLayer,
    Category,
    RevocationStatus,
    SourcePathway,
    ValidationState,
)

GATE = RetrievalGate()


def _frag(**kw):
    base = dict(fragment_id="F", title="t", content="c", category=Category.K7_sensory,
                consent=ConsentRecord(consent_status=ConsentStatus.granted),
                conditions=TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load"))
    base.update(kw)
    return TacitFragment.new(**base)


MATCH = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load", risk_class="moderate")


def _advisory(**kw):
    return _frag(authority_layer=AuthorityLayer.advisory,
                 validation_state=ValidationState.promoted_to_advisory, **kw)


def test_evidence_layer_blocked_from_operational_retrieval():
    el = GATE.evaluate(_frag(), MATCH)
    assert not el.ok and el.reason == BlockedReason.evidence_layer_not_authorised


def test_advisory_matching_allowed_nonmatching_blocked():
    assert GATE.evaluate(_advisory(), MATCH).ok
    nm = TacitContext(equipment_family="gear_pump", operating_mode="high_load", risk_class="moderate")
    assert GATE.evaluate(_advisory(), nm).reason == BlockedReason.conditions_do_not_match


def test_consent_withdrawn_blocks():
    f = _advisory(consent=ConsentRecord(consent_status=ConsentStatus.withdrawn))
    assert GATE.evaluate(f, MATCH).reason == BlockedReason.consent_withdrawn


def test_expired_review_date_blocks():
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    assert GATE.evaluate(_advisory(review_due_at=past), MATCH).reason == BlockedReason.expired_review_date


def test_revoked_blocks():
    assert GATE.evaluate(_advisory(revocation_status=RevocationStatus.superseded), MATCH).reason \
        == BlockedReason.revoked_or_superseded


def test_high_risk_requires_escalation():
    hi = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load", risk_class="high")
    assert GATE.evaluate(_advisory(), hi).reason == BlockedReason.risk_class_requires_human_escalation


def test_endogenous_evidence_requires_review():
    assert GATE.evaluate(_frag(source_pathway=SourcePathway.endogenous), MATCH).reason \
        == BlockedReason.endogenous_fragment_requires_review


def test_controlled_requires_exact_match():
    loose = _frag(authority_layer=AuthorityLayer.controlled,
                  validation_state=ValidationState.promoted_to_controlled,
                  conditions=TacitContext(equipment_family=["centrifugal_pump", "gear_pump"], operating_mode="high_load"))
    assert GATE.evaluate(loose, MATCH).reason == BlockedReason.controlled_layer_requires_exact_match


def test_exclusion_condition_applies():
    f = _advisory(conditions=TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load",
                                          exclusion_conditions=[{"shift_pattern": "night"}]))
    ctx = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load",
                       shift_pattern="night", risk_class="moderate")
    assert GATE.evaluate(f, ctx).reason == BlockedReason.exclusion_condition_applies


def test_role_not_authorised():
    f = _advisory(conditions=TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load", role="senior"))
    assert GATE.evaluate(f, MATCH, role="trainee").reason == BlockedReason.role_not_authorised


def test_retrieval_decision_is_auditable(captured_fragment):
    engine, res = captured_fragment
    engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", summary="ok")
    before = engine.adapter.chain.count
    engine.retrieve(MATCH)
    assert engine.adapter.chain.count > before
    assert any(a["kind"] == "tacit.retrieval_decision" for a in engine.adapter.artefacts.values())
