"""Workspace membership and per-reviewer votes, as a multi-user deployment uses them."""
import pytest

from metis import MetisEngine
from metis.conditions.context import TacitContext
from metis.consent.model import ConsentRecord, ConsentStatus
from metis.governance.membership import Role
from metis.taxonomy.categories import AuthorityLayer, ValidationState
from metis.validation.states import InvalidTransition

ADMIN = "human:admin@example.com"
WORKER = "human:wendy@example.com"
R1, R2, R3 = ("human:rhea@example.com", "human:raj@example.com", "human:rosa@example.com")
AGENT = "agent:shift-assistant"
CONNECTOR = "agent:cmms-connector"
PUMP = TacitContext(equipment_family="centrifugal_pump", operating_mode="high_load")


def _engine() -> MetisEngine:
    eng = MetisEngine(workspace_id="wsp_votes", name="Votes", deterministic=False, members=[],
                      escalation_assignee="group:escalation@metis.local")
    eng.join_system_participants()
    eng.set_member(WORKER, ["worker"], by=ADMIN, display_name="Wendy")
    eng.set_member(R1, ["reviewer"], by=ADMIN)
    eng.set_member(R2, ["reviewer", "escalation"], by=ADMIN)
    eng.set_member(AGENT, ["agent"], by=ADMIN)
    eng.set_member(CONNECTOR, ["capture"], by=ADMIN)
    return eng


def _capture(eng: MetisEngine, obs_id: str = "OBS-1") -> str:
    pending = eng.begin_capture(
        {"observation_id": obs_id, "work_as_imagined": "Reduce load at the alarm.",
         "work_as_done": "Ease back earlier on a dull sound.", "context": PUMP},
        consent=ConsentRecord(consent_status=ConsentStatus.pending), worker=WORKER,
        submitted_by=CONNECTOR, category="K7_sensory", conditions=PUMP)
    result = eng.answer_whisper(pending.whisper_id, response="confirm", answered_by=WORKER,
                                consent_granted=True)
    return result.fragment.fragment_id


def test_members_and_roles_are_recorded_on_the_chain():
    eng = _engine()
    assert eng.mission_group_members == [R1, R2]
    assert eng.roles_of(R2) == [Role.reviewer, Role.escalation]
    records = eng.adapter.artefacts_of_kind("tacit.membership_record")
    assert [r["content"]["participant"] for r in records] == [WORKER, R1, R2, AGENT, CONNECTOR]
    assert records[0]["content"]["granted"] == ["worker"]
    assert records[0]["content"]["actioned_by"] == ADMIN
    members = eng.adapter.coord.get_workspace(eng.adapter.workspace_id).members
    assert {WORKER, R1, R2, AGENT, CONNECTOR, ADMIN} <= set(members)


def test_roles_must_suit_the_participant_type():
    eng = _engine()
    with pytest.raises(ValueError):
        eng.set_member("agent:clever-bot", ["reviewer"], by=ADMIN)
    with pytest.raises(ValueError):
        eng.set_member("human:pat@example.com", ["agent"], by=ADMIN)
    with pytest.raises(ValueError):
        eng.set_member(WORKER, ["superuser"], by=ADMIN)


def test_the_observation_is_recorded_as_the_submitter_s():
    eng = _engine()
    _capture(eng)
    obs = eng.adapter.artefacts_of_kind("tacit.capture_observation")[0]
    assert obs["produced_by"] == CONNECTOR
    confirmation = eng.adapter.artefacts_of_kind("tacit.operator_confirmation")[0]
    assert confirmation["produced_by"] == WORKER


def test_a_promotion_completes_when_the_quorum_agrees():
    eng = _engine()
    fid = _capture(eng)
    first = eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1, summary="clear cue")
    assert first["status"] == "pending" and first["approvals"] == [R1] and first["required"] == 2
    frag = eng.fragments.require(fid)
    assert frag.validation_state == ValidationState.tier2_pending
    assert "1 of 2 approvals" in frag.lineage[-1].note
    assert eng.governance.review_approvals(fid) == {R1: "promoted_to_advisory"}

    with pytest.raises(InvalidTransition):
        eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1)
    with pytest.raises(InvalidTransition):
        eng.cast_review_vote(fid, "promoted_to_controlled", reviewer=R2,
                             change_control={"ticket": "CC-1"})
    with pytest.raises(PermissionError):
        eng.cast_review_vote(fid, "promoted_to_advisory", reviewer="human:mallory@example.com")

    second = eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R2)
    assert second["status"] == "decided" and second["decided_by"] == [R1, R2]
    frag = eng.fragments.require(fid)
    assert frag.validation_state == ValidationState.promoted_to_advisory
    assert frag.authority_layer == AuthorityLayer.advisory
    assert second["memory"].fragment_id == fid
    assert eng.verify().ok


def test_one_reviewer_holds_and_ends_the_review():
    eng = _engine()
    fid = _capture(eng)
    eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1)
    out = eng.cast_review_vote(fid, "held", reviewer=R2, summary="needs more cases")
    assert out["status"] == "decided"
    assert eng.fragments.require(fid).validation_state == ValidationState.held
    assert not eng.governance.review_open(fid)


def test_a_new_reviewer_can_vote_on_a_review_opened_before_they_joined():
    eng = _engine()
    fid = _capture(eng)
    eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1)
    eng.set_member(R3, ["reviewer"], by=ADMIN)
    out = eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R3)
    assert out["status"] == "decided" and out["decided_by"] == [R1, R3]


def test_a_removed_reviewer_can_no_longer_vote():
    eng = _engine()
    fid = _capture(eng)
    eng.set_member(R2, [], by=ADMIN, reason="left the site")
    assert eng.mission_group_members == [R1]
    assert R2 not in eng.adapter.coord.get_workspace(eng.adapter.workspace_id).members
    with pytest.raises(PermissionError):
        eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R2)
    record = eng.adapter.artefacts_of_kind("tacit.membership_record")[-1]["content"]
    assert record["revoked"] == ["reviewer", "escalation"] and record["roles"] == []


def test_membership_survives_export_and_import():
    eng = _engine()
    state = eng.export_state()
    fresh = MetisEngine(workspace_id="wsp_other", name="Other", deterministic=False, members=[])
    fresh.import_state(state)
    assert fresh.mission_group_members == [R1, R2]
    assert fresh.escalation_assignee == "group:escalation@metis.local"
    assert fresh.roles_of(AGENT) == [Role.agent]


def test_escalations_go_to_the_escalation_group():
    eng = _engine()
    fid = _capture(eng)
    eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R1)
    eng.cast_review_vote(fid, "promoted_to_advisory", reviewer=R2)
    decision = eng.retrieve(TacitContext(equipment_family="centrifugal_pump",
                                         operating_mode="high_load", risk_class="high"))
    assert decision.escalation_task_id
    task = eng.adapter.tasks[decision.escalation_task_id]
    assert task["assignee"] == "group:escalation@metis.local"


def test_a_local_project_keeps_members_and_open_proposals(tmp_path):
    from metis.project import Project

    project = Project(tmp_path / ".metis")
    engine = project.create_engine("wsp_local", name="Local", site="plant_a")
    engine.join_default_participants()
    reviewers = engine.mission_group_members
    engine.set_member(R3, ["reviewer"], by=ADMIN)
    pending = engine.begin_capture(
        {"observation_id": "OBS-L", "work_as_done": "Ease back earlier.", "context": PUMP},
        consent=ConsentRecord(consent_status=ConsentStatus.pending), category="K7_sensory",
        conditions=PUMP)
    fid = engine.answer_whisper(pending.whisper_id, response="confirm",
                                answered_by=engine.operator_uri, consent_granted=True).fragment.fragment_id
    out = engine.cast_review_vote(fid, "promoted_to_advisory", reviewer=R3,
                                  use_constraints=["Advisory only."])
    assert out["status"] == "pending"
    project.save(engine)
    project.close("wsp_local")

    reopened = project.open("wsp_local")
    assert reopened.mission_group_members == [*reviewers, R3]
    assert reopened.governance.proposals[fid]["use_constraints"] == ["Advisory only."]
    done = reopened.cast_review_vote(fid, "promoted_to_advisory", reviewer=reviewers[0])
    assert done["status"] == "decided"
    assert reopened.fragments.require(fid).use_constraints == ["Advisory only."]
    project.close("wsp_local")
