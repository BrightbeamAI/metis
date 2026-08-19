from metis.integrations.chap import compliance


def test_adapter_emits_only_catalogue_methods(manufacturing_run):
    for entry in manufacturing_run.engine.adapter.chain.entries:
        method = entry.envelope.get("method")
        if method is not None:
            assert method in compliance.CHAP_METHODS, f"non-CHAP method {method}"


def test_no_custom_protocol_envelope(manufacturing_run):
    for entry in manufacturing_run.engine.adapter.chain.entries:
        compliance.assert_no_custom_protocol(entry.envelope)
        compliance.validate_envelope(entry.envelope)


def test_artefacts_conform_to_chap_conventions(manufacturing_run):
    for art in manufacturing_run.engine.adapter.artefacts.values():
        compliance.validate_artefact(art)
    # custom tacit.* kinds carry a schema reference (CHAP requirement)
    tacit_arts = [a for a in manufacturing_run.engine.adapter.artefacts.values() if a["kind"].startswith("tacit.")]
    assert tacit_arts and all("schema" in a for a in tacit_arts)


def test_evidence_records_conform(manufacturing_run):
    for rec in manufacturing_run.engine.adapter.evidence_records():
        compliance.validate_evidence_record(rec)


def test_observation_maps_to_chap_artefact(captured_fragment):
    engine, res = captured_fragment
    obs_arts = engine.adapter.artefacts_of_kind("tacit.capture_observation")
    assert obs_arts
    compliance.validate_artefact(obs_arts[0])


def test_fragment_records_are_carried_by_coordinator_methods(manufacturing_run):
    # tacit.* artefacts ride on methods the reference Coordinator implements
    methods_for_fragment = []
    for e in manufacturing_run.engine.adapter.chain.entries:
        params = e.envelope.get("params", {})
        art = params.get("output") or params.get("artefact")
        if isinstance(art, dict) and art.get("kind") == "tacit.fragment":
            methods_for_fragment.append(e.envelope["method"])
    assert methods_for_fragment and all(m in compliance.COORDINATOR_METHODS for m in methods_for_fragment)
