import datetime as dt

import pytest

from metis import clock
from metis.fragment.confidence import evidence_confidence
from metis.fragment.model import EvidenceStrength, FragmentEvidence
from metis.scenarios import run_manufacturing

QL = "human:quality-lead@metis.local"
PE = "human:process-engineer@metis.local"
SO = "human:safety-officer@metis.local"


def _approvals(engine):
    return [e.envelope["params"]["from"] for e in engine.adapter.chain.entries
            if e.envelope.get("method") == "decide.approve"]


def test_promotion_is_a_quorum_of_named_reviewers(manufacturing_run):
    eng = manufacturing_run.engine
    assert _approvals(eng) == [QL, PE]
    record = next(a for a in eng.adapter.artefacts.values() if a["kind"] == "tacit.promotion_record")
    assert record["content"]["approvers"] == [QL, PE]
    assert record["content"]["decision_rule"] == "quorum:2"
    assert eng.verify().ok


def test_one_approver_cannot_promote(captured_fragment):
    engine, res = captured_fragment
    with pytest.raises(PermissionError, match="2 distinct"):
        engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", decided_by=[QL])
    assert not _approvals(engine)


def test_the_same_reviewer_twice_is_one_approval(captured_fragment):
    engine, res = captured_fragment
    with pytest.raises(PermissionError):
        engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", decided_by=[QL, QL])


def test_outsiders_cannot_decide(captured_fragment):
    engine, res = captured_fragment
    with pytest.raises(PermissionError, match="Not Mission Group reviewers"):
        engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory",
                            decided_by=[QL, "agent:assistant#v1"])


def test_one_reviewer_can_reject(captured_fragment):
    engine, res = captured_fragment
    out = engine.tier2_review(res.fragment.fragment_id, "rejected", decided_by=[SO], summary="unsafe")
    assert out["decided_by"] == [SO]
    rejects = [e.envelope["params"]["from"] for e in engine.adapter.chain.entries
               if e.envelope.get("method") == "decide.reject"]
    assert rejects == [SO]


def test_held_then_promoted(captured_fragment):
    engine, res = captured_fragment
    engine.tier2_review(res.fragment.fragment_id, "held", summary="need one more case")
    out = engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", summary="ok now")
    assert out["memory"].authority_layer.value == "advisory"


def test_confidence_follows_the_evidence():
    assert evidence_confidence(FragmentEvidence()) == 0.10
    moderate = FragmentEvidence(recurrence_count=4, evidence_strength=EvidenceStrength.moderate,
                                outcome_link="avoided alarms")
    assert evidence_confidence(moderate) == 0.62
    contested = moderate.model_copy(update={"counterexamples": ["c1", "c2"]})
    assert evidence_confidence(contested) < evidence_confidence(moderate)
    assert run_manufacturing().fragment.confidence == 0.62


def test_promotion_sets_a_review_date_that_expires(manufacturing_run):
    eng, frag = manufacturing_run.engine, manufacturing_run.fragment
    due = dt.datetime.fromisoformat(frag.review_due_at.replace("Z", "+00:00"))
    promoted = dt.datetime.fromisoformat(frag.lineage[-1].at.replace("Z", "+00:00"))
    assert 179 <= (due - promoted).days <= 180
    assert frag.expiry_triggers
    context = manufacturing_run.match_decision.runtime_context
    from metis.conditions.context import TacitContext
    assert eng.evaluate(frag, TacitContext(**context)).ok
    with clock.use(lambda: (due + dt.timedelta(days=1)).isoformat()):
        assert eng.gate.evaluate(frag, TacitContext(**context)).reason.value == "expired_review_date"


def test_high_risk_fragments_are_reviewed_sooner(captured_fragment):
    engine, res = captured_fragment
    res.fragment.conditions.risk_class = "high"
    engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory")
    frag = engine.fragments.require(res.fragment.fragment_id)
    due = dt.datetime.fromisoformat(frag.review_due_at.replace("Z", "+00:00"))
    promoted = dt.datetime.fromisoformat(frag.lineage[-1].at.replace("Z", "+00:00"))
    assert 89 <= (due - promoted).days <= 90


def test_provenance_names_no_model_when_none_ran(manufacturing_run):
    prov = manufacturing_run.fragment.provenance
    assert prov.model_assist_mode == "deterministic_fixture"
    assert prov.model_provider is None and prov.model_name is None
    assert prov.model_output_status == "confirmed_by_worker"
    assert prov.human_review_status == "promoted_to_advisory"


def test_every_lineage_entry_links_to_the_chain(manufacturing_run):
    lineage = manufacturing_run.fragment.lineage
    assert all(e.chap_artefact_ref for e in lineage)
    assert all(e.chap_evidence_seq is not None for e in lineage)
