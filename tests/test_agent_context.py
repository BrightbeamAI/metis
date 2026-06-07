import jsonschema

from tacitflow.memory.agent_context import AgentMemoryContext


def test_agent_context_schema_validates(manufacturing_run):
    amc = manufacturing_run.agent_context
    jsonschema.validate(amc.model_dump(mode="json"), AgentMemoryContext.model_json_schema())


def test_agent_context_keeps_memory_types_distinct(manufacturing_run):
    amc = manufacturing_run.agent_context
    # the four memory types are separate fields
    for field in ("procedural_memory", "semantic_memory", "episodic_memory", "tacit_memory"):
        assert hasattr(amc, field)
    # tacit entries carry use constraints and audit refs
    t = amc.tacit_memory[0]
    assert t.use_constraints
    assert t.audit_refs


def test_required_human_actions_surface(manufacturing_run):
    amc = manufacturing_run.agent_context
    joined = " ".join(amc.required_human_actions).lower()
    assert "confirm" in joined or "escalate" in joined
