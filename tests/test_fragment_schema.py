import jsonschema
import pytest
from pydantic import ValidationError

from metis.consent.model import ConsentRecord, ConsentStatus
from metis.fragment.model import TacitFragment
from metis.memory.tacit import AgentVisibility, TacitMemoryObject
from metis.taxonomy.categories import AuthorityLayer, Category, ValidationState


def test_fragment_requires_core_fields():
    with pytest.raises(ValidationError):
        TacitFragment(title="x")  # missing required fields


def test_fragment_round_trips_and_validates_against_json_schema():
    f = TacitFragment.new(fragment_id="TF-9", title="t", content="c", category=Category.K7_sensory)
    schema = TacitFragment.model_json_schema()
    jsonschema.validate(f.model_dump(mode="json"), schema)
    again = TacitFragment.model_validate(f.model_dump())
    assert again.fragment_id == "TF-9"
    assert again.domain == f.domain


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        TacitFragment.new(fragment_id="TF-x", title="t", content="c",
                          category=Category.K7_sensory, confidence=1.5)


def test_tacit_memory_object_schema_and_visibility():
    f = TacitFragment.new(fragment_id="TF-10", title="t", content="c", category=Category.K7_sensory,
                          consent=ConsentRecord(consent_status=ConsentStatus.granted),
                          authority_layer=AuthorityLayer.advisory,
                          validation_state=ValidationState.promoted_to_advisory)
    mo = TacitMemoryObject.from_fragment(f, memory_id="TM-1")
    jsonschema.validate(mo.model_dump(mode="json"), TacitMemoryObject.model_json_schema())
    assert mo.agent_visibility == AgentVisibility.advisory_context
    assert mo.memory_type == "tacit"
