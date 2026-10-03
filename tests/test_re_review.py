"""Fragments in use go back before the Mission Group: renewal, layer moves, hold, rejection,
re-elicitation, and contests the reviewers decide."""
import pytest

from metis.consent.contestability import ContestAction
from metis.project import Project
from metis.scenarios import SPECS, run_spec
from metis.validation.states import InvalidTransition

QL = "human:quality-lead@metis.local"
PE = "human:process-engineer@metis.local"
SO = "human:safety-officer@metis.local"
QUORUM = [QL, PE]
CHANGE = {"change_id": "CC-104", "procedure": "SOP-17 rev 4"}


def _promote(engine, res):
    engine.tier2_review(res.fragment.fragment_id, "promoted_to_advisory", summary="ok",
                        decided_by=QUORUM)
    return engine.fragments.get(res.fragment.fragment_id)


def _review_requests(engine, task_id):
    return [e for e in engine.adapter.chain.entries
            if e.envelope.get("method") == "review.request"
            and (e.envelope.get("params") or {}).get("task_id") == task_id]


def test_renewal_after_the_review_date_puts_the_fragment_back_in_use(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    memory_id = engine.tacit_store.by_fragment(frag.fragment_id)[0].memory_id
    frag.review_due_at = "2000-01-01T00:00:00+00:00"
    assert engine.evaluate(frag, match_context).reason.value == "expired_review_date"

    out = engine.tier2_review(frag.fragment_id, "promoted_to_advisory", summary="still holds",
                              decided_by=QUORUM)

    assert engine.evaluate(frag, match_context).ok
    assert frag.review_due_at > "2000-01-01"
    assert frag.lineage[-1].note.startswith("renewed by the Mission Group")
    assert engine.adapter.tasks[out["review_task"]]["kind"] == "tacit.validate.tier2"
    assert _review_requests(engine, out["review_task"])
    memories = engine.tacit_store.by_fragment(frag.fragment_id)
    assert [m.memory_id for m in memories] == [memory_id]
    assert memories[0].review_due_at == frag.review_due_at
    assert engine.verify().ok


def test_renewal_still_needs_the_quorum(captured_fragment):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    before = engine.adapter.chain.count
    with pytest.raises(PermissionError, match="2 distinct"):
        engine.tier2_review(frag.fragment_id, "promoted_to_advisory", decided_by=[QL])
    assert engine.adapter.chain.count == before


def test_advisory_moves_to_controlled_with_change_control(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    before = engine.adapter.chain.count
    with pytest.raises(PermissionError, match="change-control"):
        engine.tier2_review(frag.fragment_id, "promoted_to_controlled", decided_by=QUORUM)
    assert engine.adapter.chain.count == before  # refused before anything was recorded

    out = engine.tier2_review(frag.fragment_id, "promoted_to_controlled", decided_by=QUORUM,
                              change_control=CHANGE, summary="incorporated into SOP-17")
    assert frag.authority_layer.value == "controlled"
    assert frag.validation_state.value == "promoted_to_controlled"
    assert frag.lineage[-1].note.startswith("moved from advisory to controlled")
    assert out["memory"].agent_visibility.value == "controlled_instruction"
    assert len(engine.tacit_store.by_fragment(frag.fragment_id)) == 1
    assert engine.evaluate(frag, match_context).ok

    engine.tier2_review(frag.fragment_id, "promoted_to_advisory", decided_by=QUORUM,
                        summary="procedure withdrawn; advisory again")
    assert frag.authority_layer.value == "advisory"
    assert frag.lineage[-1].note.startswith("moved from controlled to advisory")
    assert engine.verify().ok


def test_a_hold_suspends_use_and_a_later_promotion_reinstates_it(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    engine.tier2_review(frag.fragment_id, "held", decided_by=[SO], summary="new pump model")
    assert frag.validation_state.value == "held"
    assert not engine.evaluate(frag, match_context).ok
    assert engine.tacit_store.by_fragment(frag.fragment_id)[0].agent_visibility.value == "hidden"

    engine.tier2_review(frag.fragment_id, "promoted_to_advisory", decided_by=QUORUM,
                        summary="checked on the new model")
    memories = engine.tacit_store.by_fragment(frag.fragment_id)
    assert len(memories) == 1 and memories[0].agent_visibility.value == "advisory_context"
    assert engine.evaluate(frag, match_context).ok
    assert engine.verify().ok


def test_one_reviewer_can_reject_a_fragment_in_use(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    out = engine.tier2_review(frag.fragment_id, "rejected", decided_by=[SO], summary="unsafe now")
    assert out["rejection_record"].startswith("art_")
    assert frag.validation_state.value == "rejected"
    assert frag.revocation_status.value == "rejected"
    assert frag.authority_layer.value == "evidence"
    assert not engine.evaluate(frag, match_context).ok
    assert engine.tacit_store.by_fragment(frag.fragment_id)[0].revocation_status.value == "rejected"
    assert engine.verify().ok


def test_re_elicitation_of_a_fragment_in_use(captured_fragment, match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    engine.tier2_review(frag.fragment_id, "re_elicit", decided_by=[PE], summary="cue unclear")
    assert frag.validation_state.value == "re_elicit"
    assert frag.revocation_status.value == "under_re_elicitation"
    assert not engine.evaluate(frag, match_context).ok
    re_elicit = [t for t in engine.adapter.tasks.values() if t["kind"] == "tacit.re_elicit"]
    assert re_elicit and re_elicit[-1]["assignee"] == PE
    assert engine.verify().ok


def test_a_contest_on_a_fragment_in_use_opens_a_review_the_reviewers_decide(captured_fragment,
                                                                          match_context):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    out = engine.governance.contest(frag.fragment_id, ContestAction.challenge,
                                    raised_by=engine.operator_uri, rationale="the cue changed")
    task = out["mission_group_task"]
    assert engine.adapter.tasks[task]["kind"] == "tacit.validate.tier2"
    assert engine.adapter.tasks[task]["assignee"] == engine.mission_group_uri
    assert _review_requests(engine, task)
    assert engine.governance.review_open(frag.fragment_id)
    assert engine.evaluate(frag, match_context).ok  # still in use while the review is open

    again = engine.governance.contest(frag.fragment_id, ContestAction.correct,
                                      raised_by=engine.operator_uri, rationale="and the wording")
    assert again["mission_group_task"] == task  # joins the open review

    decision = engine.tier2_review(frag.fragment_id, "promoted_to_advisory", decided_by=QUORUM,
                                   summary="kept after checking the cue")
    assert decision["review_task"] == task
    assert not engine.governance.review_open(frag.fragment_id)
    assert engine.verify().ok


def test_a_contest_on_a_closed_fragment_keeps_the_record(captured_fragment):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    engine.tier2_review(frag.fragment_id, "rejected", decided_by=[SO], summary="unsafe")
    out = engine.governance.contest(frag.fragment_id, ContestAction.challenge,
                                    raised_by=engine.operator_uri, rationale="please look again")
    assert out["contestability_record"].startswith("art_")
    assert "mission_group_task" not in out
    with pytest.raises(InvalidTransition):
        engine.request_review(frag.fragment_id)


def test_an_open_re_review_survives_a_restart(tmp_path):
    spec = SPECS["manufacturing-pump-vibration"]
    project = Project(tmp_path)
    engine = project.create_engine(spec.workspace_id, name=spec.name, site=spec.site)
    run = run_spec(spec, engine=engine)
    fragment_id = run.fragment.fragment_id
    task = engine.request_review(fragment_id, reason="annual review")
    project.save(engine)
    project.close(spec.workspace_id)

    reopened = project.open(spec.workspace_id)
    assert reopened.governance.review_open(fragment_id)
    out = reopened.tier2_review(fragment_id, "promoted_to_advisory", decided_by=QUORUM,
                                summary="renewed at the annual review")
    assert out["review_task"] == task
    assert reopened.verify().ok


def test_naming_more_approvers_than_the_quorum_records_the_ones_that_count(captured_fragment):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    out = engine.tier2_review(frag.fragment_id, "promoted_to_advisory", decided_by=[QL, PE, SO],
                              summary="renewed by all three")
    assert out["decided_by"] == [QL, PE]
    assert not engine.governance.review_open(frag.fragment_id)
    engine.tier2_review(frag.fragment_id, "held", decided_by=[SO], summary="later concern")
    assert frag.validation_state.value == "held"
    assert engine.verify().ok


def test_a_revoked_fragment_is_out_of_review(captured_fragment):
    from metis.consent.revocation import RevocationReason

    engine, res = captured_fragment
    frag = _promote(engine, res)
    engine.governance.revoke(frag.fragment_id, reason=RevocationReason.safety_concern, by=SO)
    before = engine.adapter.chain.count
    with pytest.raises(InvalidTransition):
        engine.tier2_review(frag.fragment_id, "promoted_to_advisory", decided_by=QUORUM)
    with pytest.raises(InvalidTransition):
        engine.request_review(frag.fragment_id)
    assert engine.adapter.chain.count == before
    out = engine.governance.contest(frag.fragment_id, ContestAction.challenge,
                                    raised_by=engine.operator_uri, rationale="look again")
    assert "mission_group_task" not in out


def test_revocation_ends_an_open_re_review_in_chap(captured_fragment):
    from metis.consent.revocation import RevocationReason

    engine, res = captured_fragment
    frag = _promote(engine, res)
    task = engine.request_review(frag.fragment_id, reason="annual review")
    assert engine.adapter.task_state(task) == "review_requested"
    engine.governance.revoke(frag.fragment_id, reason=RevocationReason.drift, by=SO)
    assert engine.adapter.task_state(task) == "cancelled"
    assert not engine.governance.review_open(frag.fragment_id)
    assert engine.verify().ok


def test_rejection_moves_the_memory_object_with_the_fragment(captured_fragment):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    engine.tier2_review(frag.fragment_id, "rejected", decided_by=[SO], summary="unsafe")
    memory = engine.tacit_store.by_fragment(frag.fragment_id)[0]
    assert memory.authority_layer.value == "evidence"
    assert memory.agent_visibility.value == "hidden"


def test_a_contest_is_recorded_on_the_review_it_opens(captured_fragment):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    out = engine.governance.contest(frag.fragment_id, ContestAction.challenge,
                                    raised_by=engine.operator_uri, rationale="the cue changed")
    record = engine.adapter.artefacts[out["contestability_record"]]
    assert record["task"] == out["mission_group_task"]


def test_a_held_fragment_is_reinstated(captured_fragment):
    engine, res = captured_fragment
    frag = _promote(engine, res)
    engine.tier2_review(frag.fragment_id, "held", decided_by=[SO], summary="pause")
    engine.tier2_review(frag.fragment_id, "promoted_to_advisory", decided_by=QUORUM,
                        summary="resume")
    assert frag.lineage[-1].note.startswith("reinstated by the Mission Group")


def test_a_review_task_closed_without_a_decision_is_reopened(captured_fragment):
    engine, res = captured_fragment
    fragment_id = res.fragment.fragment_id
    first = engine.request_review(fragment_id)
    engine.adapter.cancel_task(first, sender=engine.mission_group_uri, reason="lost")
    out = engine.tier2_review(fragment_id, "promoted_to_advisory", decided_by=QUORUM,
                              summary="decided on the reopened review")
    assert out["review_task"] != first
    assert res.fragment.validation_state.value == "promoted_to_advisory"
    assert engine.verify().ok
