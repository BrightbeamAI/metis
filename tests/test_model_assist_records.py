import jsonschema

from metis.models.structured_outputs import AssistPurpose, ModelAssistRecord


def test_model_assist_record_schema():
    rec = ModelAssistRecord(assist_id="MA-1", provider="ollama", model_name="gemma4",
                            model_url="http://localhost:11434", purpose=AssistPurpose.draft_whisper,
                            prompt_template="t")
    jsonschema.validate(rec.model_dump(mode="json"), ModelAssistRecord.model_json_schema())
    assert rec.human_review_required is True
    assert rec.human_review_status == "pending"


def test_capture_with_model_creates_assist_records(captured_fragment):
    engine, res = captured_fragment
    assert len(res.model_assist_records) >= 1
    kinds = [a["kind"] for a in engine.adapter.artefacts.values()]
    assert "tacit.model_assist_record" in kinds
    # provenance, not authority: fragment records the assist refs
    assert res.fragment.provenance.model_assist_refs


def test_model_output_cannot_promote_or_authorise(captured_fragment):
    """A ModelAssistRecord carries no authority; only the Mission Group promotes."""
    engine, res = captured_fragment
    # fragment is still Evidence-layer right after capture, despite model assistance
    assert res.fragment.authority_layer.value == "evidence"
    # there is no API by which a model promotes; promotion requires tier2_review (human/group)
    assert not hasattr(engine.model_client, "promote")
    record = res.model_assist_records[0]
    assert record.human_review_required is True
