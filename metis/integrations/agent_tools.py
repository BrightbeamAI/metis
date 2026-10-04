"""Metis as tools for any model that calls functions.

``MetisToolbox`` describes three tools in the formats the OpenAI and Anthropic APIs take, and
runs a call the model makes through the Metis client. The tools return the same governed views
as the server: guidance only where its conditions match, with its use constraints, and any
decision a person must make.

    from metis.client import MetisClient
    from metis.integrations.agent_tools import MetisToolbox

    toolbox = MetisToolbox(MetisClient(url, api_key=key), workspace="wsp_plant_a")
    tools = toolbox.anthropic_tools()        # or toolbox.openai_tools()
    ...                                      # the model asks for a tool
    result = toolbox.call(name, arguments)   # a JSON-safe dict to send back

Agents that speak MCP can use the server's remote MCP endpoint (``/mcp``) instead.
"""
from __future__ import annotations

import json
from typing import Any

CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "The current work situation. Give every field you know, and always the risk class: the "
        "gate returns guidance only where its recorded conditions match, an unknown value does "
        "not count as a match, and high-risk situations go to a person."),
    "properties": {
        "site": {"type": "string"},
        "area": {"type": "string"},
        "line": {"type": "string"},
        "equipment_family": {"type": "string", "description": "for example centrifugal_pump"},
        "equipment_id": {"type": "string"},
        "product_family": {"type": "string"},
        "material_lot": {"type": "string"},
        "operating_mode": {"type": "string", "description": "for example high_load or startup"},
        "shift_pattern": {"type": "string"},
        "role": {"type": "string"},
        "risk_class": {"type": "string", "enum": ["low", "moderate", "high", "critical"]},
        "trigger_context": {"type": "string", "description": "what prompted the question"},
        "environmental_conditions": {
            "type": "object", "additionalProperties": {"type": "string"},
            "description": "other measured conditions, for example {\"ambient_temp\": \"hot\"}"},
    },
    "required": ["risk_class"],
    "additionalProperties": False,
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "metis_retrieve_guidance",
        "description": (
            "Ask Metis for governed tacit guidance (reviewed accounts of expert practice) for the "
            "current work situation. Returns guidance with its use constraints, which you must "
            "honour, and required_human_actions: when it lists anything, stop and wait for the "
            "person's decision (metis_check_escalation reports it)."),
        "parameters": {"type": "object", "properties": {"context": CONTEXT_SCHEMA},
                       "required": ["context"]},
    },
    {
        "name": "metis_agent_memory_context",
        "description": (
            "Assemble procedural, semantic, episodic, and governed tacit memory for a task in the "
            "current work situation, with any required human actions."),
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description": "a short identifier for your task"},
            "context": CONTEXT_SCHEMA}, "required": ["task", "context"]},
    },
    {
        "name": "metis_check_escalation",
        "description": (
            "The state of an escalation Metis opened for you, and the person's decision once made: "
            "applies, does_not_apply, or refer_to_review. After applies, ask for guidance again "
            "with the same context to receive it; otherwise do not use the withheld guidance."),
        "parameters": {"type": "object", "properties": {
            "task_id": {"type": "string", "description": "escalation_task_id from a retrieval"}},
            "required": ["task_id"]},
    },
]


class MetisToolbox:
    """The Metis tools for one workspace, run through a ``MetisClient``."""

    def __init__(self, client: Any, workspace: str) -> None:
        self.client = client
        self.workspace = workspace

    def openai_tools(self) -> list[dict[str, Any]]:
        """Function tools for the OpenAI Chat Completions API."""
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["parameters"]}} for t in TOOLS]

    def openai_responses_tools(self) -> list[dict[str, Any]]:
        """Function tools for the OpenAI Responses API."""
        return [{"type": "function", "name": t["name"], "description": t["description"],
                 "parameters": t["parameters"]} for t in TOOLS]

    def anthropic_tools(self) -> list[dict[str, Any]]:
        """Tools for the Anthropic Messages API."""
        return [{"name": t["name"], "description": t["description"],
                 "input_schema": t["parameters"]} for t in TOOLS]

    def call(self, name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
        """Run the tool a model asked for; return a JSON-safe result for the model. A refusal or
        a bad argument comes back as ``{"error": ..., "status": ...}`` for the model to read,
        so it ends no agent run."""
        from ..client import MetisError

        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
            if name == "metis_retrieve_guidance":
                return self.client.retrieve(self.workspace, args["context"])
            if name == "metis_agent_memory_context":
                return self.client.agent_context(self.workspace, args["task"], args["context"])
            if name == "metis_check_escalation":
                return self.client.escalation(self.workspace, args["task_id"])
            return {"error": f"Unknown Metis tool: {name}", "status": 400}
        except MetisError as exc:
            return {"error": exc.detail, "status": exc.status}
        except (KeyError, TypeError, ValueError) as exc:
            missing = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
            return {"error": f"Invalid arguments for {name}: {missing}", "status": 400}
