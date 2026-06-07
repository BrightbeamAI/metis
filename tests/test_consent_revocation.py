from tacitflow.consent.revocation import RevocationReason
from tacitflow.retrieval.gate import RetrievalGate
from tacitflow.taxonomy.categories import RevocationStatus

GATE = RetrievalGate()


def _promote(engine, res):
    engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", summary="ok")
    return res.fragment


def test_withdrawn_consent_blocks_retrieval(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    assert GATE.evaluate(frag, match_context).ok
    engine.governance.withdraw_consent(frag.fragment_id, by="human:operator@plant_a")
    assert not GATE.evaluate(frag, match_context).ok


def test_revocation_blocks_future_retrieval(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    engine.governance.revoke(frag.fragment_id, reason=RevocationReason.retired, by="human:reviewer@plant_a")
    assert frag.revocation_status == RevocationStatus.retired
    assert not GATE.evaluate(frag, match_context).ok


def test_revocation_record_retained_and_auditable(captured_fragment):
    engine, res = captured_fragment
    _promote(engine, res)
    before = engine.adapter.chain.count
    engine.governance.revoke(res.fragment.fragment_id, reason=RevocationReason.drift, by="human:reviewer@plant_a")
    assert engine.adapter.chain.count > before
    assert any(a["kind"] == "tacit.revocation_record" for a in engine.adapter.artefacts.values())
    # control event emitted
    methods = [e.envelope.get("method") for e in engine.adapter.chain.entries]
    assert "control.cancel" in methods


def test_supersession(captured_fragment):
    engine, res = captured_fragment
    _promote(engine, res)
    engine.governance.supersede(res.fragment.fragment_id, "TF-NEW", by="group:mission-group@tacitflow.local")
    assert res.fragment.revocation_status == RevocationStatus.superseded
    assert any(a["kind"] == "tacit.supersession_record" for a in engine.adapter.artefacts.values())
