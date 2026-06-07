from tacitflow.audit.replay import replay
from tacitflow.scenarios import SCENARIOS, run_manufacturing


def test_demo_runs_end_to_end_and_produces_replayable_evidence(tmp_path):
    run = run_manufacturing()
    assert run.fragment.fragment_id and run.memory.memory_id
    assert len(run.steps) == 19
    out = tmp_path / "evidence.jsonl"
    run.engine.export_audit(str(out))
    assert replay(out).ok


def test_demo_match_and_nonmatch(tmp_path):
    run = run_manufacturing()
    assert len(run.match_decision.eligible) == 1
    assert len(run.match_decision.blocked) == 0
    assert len(run.nonmatch_decision.eligible) == 0
    assert run.nonmatch_decision.blocked[0].reason == "conditions_do_not_match"


def test_all_scenarios_run_and_verify():
    for key, runner in SCENARIOS.items():
        run = runner()
        assert run.engine.verify().ok, key
        assert run.fragment is not None, key
