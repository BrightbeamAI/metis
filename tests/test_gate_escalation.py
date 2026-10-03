from metis.conditions.context import TacitContext


def _ctx(base, **overrides):
    data = {**base, **overrides}
    return TacitContext(**{k: v for k, v in data.items() if v is not None})


def test_non_applicable_fragment_is_not_an_escalation_even_at_high_risk(manufacturing_run):
    frag = manufacturing_run.fragment
    base = manufacturing_run.match_decision.runtime_context
    el = manufacturing_run.engine.evaluate(frag, _ctx(base, equipment_family="gear_pump", equipment_id=None, risk_class="high"))
    assert el.reason.value == "conditions_do_not_match"
    assert el.escalate is False


def test_applicable_fragment_at_high_risk_escalates(manufacturing_run):
    frag = manufacturing_run.fragment
    base = manufacturing_run.match_decision.runtime_context
    el = manufacturing_run.engine.evaluate(frag, _ctx(base, risk_class="high"))
    assert el.reason.value == "risk_class_requires_human_escalation"
    assert el.escalate is True


def test_near_miss_same_pump_different_situation_escalates(manufacturing_run):
    frag = manufacturing_run.fragment
    base = manufacturing_run.match_decision.runtime_context
    el = manufacturing_run.engine.evaluate(frag, _ctx(base, operating_mode="low_load"))
    assert el.reason.value == "conditions_do_not_match" and el.near_miss and el.escalate


def test_unknown_situation_value_is_a_near_miss(manufacturing_run):
    frag = manufacturing_run.fragment
    base = manufacturing_run.match_decision.runtime_context
    el = manufacturing_run.engine.evaluate(frag, _ctx(base, operating_mode=None))
    assert el.reason.value == "conditions_do_not_match" and el.escalate


def test_exclusion_escalates(manufacturing_run):
    frag = manufacturing_run.fragment
    base = manufacturing_run.match_decision.runtime_context
    el = manufacturing_run.engine.evaluate(frag, _ctx(base, operating_mode=["high_load", "startup"]))
    assert el.reason.value == "exclusion_condition_applies" and el.escalate


def test_unauthorised_role_is_blocked_not_escalated(manufacturing_run):
    frag = manufacturing_run.fragment
    base = manufacturing_run.match_decision.runtime_context
    el = manufacturing_run.engine.evaluate(frag, _ctx(base, role="visitor"))
    assert not el.ok and el.escalate is False


def test_retrieve_opens_one_recorded_escalation_task(manufacturing_run):
    eng = manufacturing_run.engine
    base = manufacturing_run.match_decision.runtime_context
    decision = eng.retrieve(_ctx(base, risk_class="high"))
    assert decision.escalation_task_id
    task = eng.adapter.tasks[decision.escalation_task_id]
    assert task["kind"] == "tacit.escalation" and task["assignee"] == eng.operator_uri
    assert decision.required_human_actions and decision.escalation_task_id in decision.required_human_actions[0]
    assert eng.verify().ok


def test_agent_context_carries_escalation_and_human_action(manufacturing_run):
    eng = manufacturing_run.engine
    base = manufacturing_run.match_decision.runtime_context
    amc = eng.agent_context("tsk_escalation_check", _ctx(base, operating_mode="low_load"))
    assert not amc.tacit_memory
    assert amc.blocked_tacit_memory[0].escalate
    assert amc.escalation_task_id
    assert any("A person decides" in a for a in amc.required_human_actions)


def test_no_escalation_when_nothing_is_flagged(manufacturing_run):
    eng = manufacturing_run.engine
    base = manufacturing_run.match_decision.runtime_context
    decision = eng.retrieve(TacitContext(**base))
    assert decision.escalation_task_id is None and not decision.required_human_actions
