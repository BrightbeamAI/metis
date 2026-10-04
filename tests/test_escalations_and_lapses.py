"""People decide escalated retrievals; unanswered whispers lapse at their deadline."""
import datetime as dt

import pytest

from metis import MetisEngine
from metis.conditions.context import TacitContext
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.taxonomy.categories import ValidationState
from metis.validation.states import InvalidTransition

ADMIN = "human:admin@example.com"
WORKER, R1, R2 = "human:wendy@example.com", "human:rhea@example.com", "human:raj@example.com"
AGENT = "agent:shift-assistant"
PUMP = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load")
RISKY = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load",
                     risk_class="high")


def _engine(**kw) -> MetisEngine:
    eng = MetisEngine(workspace_id="wsp_esc", name="Esc", deterministic=False, members=[],
                      escalation_assignee="group:escalation@metis.local", **kw)
    eng.join_system_participants()
    eng.set_member(WORKER, ["worker"], by=ADMIN)
    eng.set_member(R1, ["reviewer"], by=ADMIN)
    eng.set_member(R2, ["reviewer", "escalation"], by=ADMIN)
    eng.set_member(AGENT, ["agent"], by=ADMIN)
    return eng


def _ask(eng, obs_id="OBS-1"):
    return eng.begin_capture(
        {"observation_id": obs_id, "work_as_done": "Ease back earlier.", "context": PUMP},
        consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=WORKER,
        category="K7_sensory", conditions=PUMP)


def _promoted(eng) -> str:
    pending = _ask(eng)
    fid = eng.answer_whisper(pending.whisper_id, response="confirm", answered_by=WORKER,
                             consent_granted=True).fragment.fragment_id
    eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1)
    eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R2)
    return fid


def test_a_person_decides_an_escalated_retrieval():
    eng = _engine()
    fid = _promoted(eng)
    decision = eng.retrieve(RISKY, requester=AGENT)
    task = decision.escalation_task_id
    [open_item] = eng.escalation_tasks()
    assert open_item["task_id"] == task and open_item["requested_by"] == AGENT
    assert open_item["decision"] is None

    with pytest.raises(PermissionError):
        eng.decide_escalation(task, "applies", by=AGENT, rationale="I think so")
    out = eng.decide_escalation(task, "applies", by=R2, rationale="Low flow, safe to ease back.")
    assert out["decision"]["outcome"] == "applies" and out["decision"]["fragments"] == [fid]
    assert eng.escalation_tasks() == []
    [closed] = eng.escalation_tasks(open_only=False)
    assert closed["state"] == "completed" and closed["decision"]["decided_by"] == R2
    with pytest.raises(InvalidTransition):
        eng.decide_escalation(task, "does_not_apply", by=R2, rationale="changed my mind")
    with pytest.raises(KeyError):
        eng.decide_escalation("tsk_nowhere", "applies", by=R2, rationale="x")
    assert eng.verify().ok


def test_referring_an_escalation_opens_a_review_and_the_fragment_stays_in_use():
    eng = _engine()
    fid = _promoted(eng)
    task = eng.retrieve(RISKY, requester=AGENT).escalation_task_id
    out = eng.decide_escalation(task, "refer_to_review", by=R2,
                                rationale="The conditions should exclude high risk explicitly.")
    assert out["decision"]["review_tasks"]
    assert eng.governance.review_open(fid)
    assert eng.fragments.require(fid).validation_state == ValidationState.promoted_to_advisory


def test_an_unanswered_whisper_lapses_at_its_deadline():
    eng = _engine(whisper_deadline_ms=60 * 60 * 1000)
    pending = _ask(eng)
    now = dt.datetime.now(dt.timezone.utc)
    assert eng.overdue_whispers(now) == []
    assert eng.lapse_whispers(now) == []
    later = now + dt.timedelta(hours=2)
    assert eng.overdue_whispers(later) == [pending.whisper_id]
    assert eng.lapse_whispers(later) == [pending.whisper_id]
    assert pending.whisper_id not in eng.pending_captures
    events = [a["content"] for a in eng.adapter.artefacts_of_kind("tacit.validation_event")]
    assert events[-1]["event"] == "whisper_lapsed" and events[-1]["worker"] == WORKER
    methods = [e.envelope.get("method") for e in eng.adapter.chain.entries]
    assert "notify.message" in methods
    with pytest.raises(KeyError):
        eng.answer_whisper(pending.whisper_id, response="confirm", answered_by=WORKER)
    assert eng.lapse_whispers(later) == [] and eng.verify().ok


def test_an_open_escalation_is_reused_and_a_decision_holds_for_the_same_situation():
    eng = _engine(escalation_grant_hours=12)
    fid = _promoted(eng)
    first = eng.retrieve(RISKY, requester=AGENT)
    again = eng.retrieve(RISKY, requester=AGENT)
    assert first.escalation_task_id == again.escalation_task_id
    assert len(eng.escalation_tasks()) == 1  # one person, asked once
    eng.decide_escalation(first.escalation_task_id, "applies", by=R2, rationale="Low flow.")
    granted = eng.retrieve(RISKY, requester=AGENT)
    assert [e.fragment_id for e in granted.eligible] == [fid]
    assert granted.escalation_decisions == {fid: first.escalation_task_id}
    assert granted.escalation_task_id is None and granted.required_human_actions == []
    recorded = eng.adapter.artefacts_of_kind("tacit.retrieval_decision")[-1]["content"]
    assert recorded["escalation_decisions"] == {fid: first.escalation_task_id}
    other = eng.retrieve(RISKY, requester="agent:another")  # another requester asks afresh
    assert other.escalation_task_id not in (None, first.escalation_task_id)
    now = dt.datetime.now(dt.timezone.utc)
    situation = granted.runtime_context
    assert eng.escalations.decided(AGENT, situation, now + dt.timedelta(hours=11)).applies \
        == {fid: first.escalation_task_id}
    assert eng.escalations.decided(AGENT, situation, now + dt.timedelta(hours=13)).applies == {}


def test_a_decision_that_guidance_does_not_apply_is_not_asked_again():
    eng = _engine()
    fid = _promoted(eng)
    task = eng.retrieve(RISKY, requester=AGENT).escalation_task_id
    eng.decide_escalation(task, "does_not_apply", by=R2, rationale="Not at this flow.")
    after = eng.retrieve(RISKY, requester=AGENT)
    assert not after.eligible and after.escalation_task_id is None
    [withheld] = after.blocked
    assert withheld.fragment_id == fid and not withheld.escalate
    assert "does not apply" in withheld.detail

