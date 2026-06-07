from tacitflow.taxonomy.categories import AuthorityLayer, ValidationState


def test_observation_creates_observation_artefact(captured_fragment):
    engine, res = captured_fragment
    kinds = [a["kind"] for a in engine.adapter.artefacts.values()]
    assert "tacit.capture_observation" in kinds
    assert res.observation.observation_id == "OBS-T1"


def test_inference_creates_only_a_candidate(captured_fragment):
    engine, res = captured_fragment
    assert res.candidate.is_hypothesis is True
    assert 0.0 <= res.candidate.confidence < 0.6  # a hypothesis, low confidence
    kinds = [a["kind"] for a in engine.adapter.artefacts.values()]
    assert "tacit.inference_candidate" in kinds


def test_whisper_uses_chap_whisper_method_not_a_parallel_mechanism(captured_fragment):
    engine, res = captured_fragment
    methods = [e.envelope.get("method") for e in engine.adapter.chain.entries]
    assert "whisper.ask" in methods
    assert "whisper.answer" in methods
    # no invented whisper method
    assert all(m is None or "." in m for m in methods)


def test_operator_confirmation_artefact_created(captured_fragment):
    engine, res = captured_fragment
    kinds = [a["kind"] for a in engine.adapter.artefacts.values()]
    assert "tacit.operator_confirmation" in kinds


def test_remember_creates_evidence_layer_fragment(captured_fragment):
    engine, res = captured_fragment
    assert res.fragment.authority_layer == AuthorityLayer.evidence
    assert res.fragment.validation_state == ValidationState.tier1_confirmed
    kinds = [a["kind"] for a in engine.adapter.artefacts.values()]
    assert "tacit.fragment" in kinds


def test_dismiss_does_not_create_fragment(engine, granted_consent, match_context):
    res = engine.capture_observation(
        dict(observation_id="OBS-D", work_as_done="something", context=match_context),
        consent=granted_consent, response="dismiss", category="K7_sensory")
    assert res.fragment is None
