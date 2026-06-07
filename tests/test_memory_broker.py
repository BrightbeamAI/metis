from tacitflow.taxonomy.categories import AuthorityLayer


def test_broker_queries_all_four_stores(manufacturing_run, match_context=None):
    run = manufacturing_run
    eng = run.engine
    ctx = run.match_decision.runtime_context
    from tacitflow.conditions.context import TacitContext
    amc = eng.agent_context("tsk_q", TacitContext.model_validate(ctx), emit=False)
    assert len(amc.procedural_memory) >= 1
    assert len(amc.semantic_memory) >= 1
    assert len(amc.episodic_memory) >= 1
    assert len(amc.tacit_memory) == 1


def test_broker_exposes_tacit_only_through_gate(manufacturing_run):
    run = manufacturing_run
    eng = run.engine
    from tacitflow.conditions.context import TacitContext
    nm = TacitContext(site="plant_a", equipment_family="gear_pump", operating_mode="low_load", risk_class="moderate")
    amc = eng.agent_context("tsk_q2", nm, emit=False)
    assert len(amc.tacit_memory) == 0
    assert len(amc.blocked_tacit_memory) == 1  # blocked but recorded
    assert amc.blocked_tacit_memory[0].reason == "conditions_do_not_match"


def test_evidence_layer_cannot_become_agent_visible_memory(captured_fragment):
    engine, res = captured_fragment
    import pytest

    from tacitflow.memory.tacit import TacitMemoryObject
    with pytest.raises(ValueError):
        TacitMemoryObject.from_fragment(res.fragment, memory_id="TM-X")


def test_advisory_fragment_becomes_advisory_memory(captured_fragment):
    engine, res = captured_fragment
    out = engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", summary="ok")
    assert out["memory"].authority_layer == AuthorityLayer.advisory
    assert out["memory"].agent_visibility.value == "advisory_context"
