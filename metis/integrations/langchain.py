"""Metis for LangChain and LangGraph: structured tools and a retriever.

    from metis.client import MetisClient
    from metis.integrations.langchain import MetisRetriever, metis_tools

    client = MetisClient(url, api_key=key)
    tools = metis_tools(client, "wsp_plant_a")          # give these to an agent
    retriever = MetisRetriever(client=client, workspace="wsp_plant_a",
                               context_provider=lambda: current_situation())

The retriever returns one ``Document`` per piece of guidance, with its use constraints in the
metadata. When a person must decide first, it returns a document of type
``required_human_action`` in their place, so a chain cannot act on guidance a person has yet to
decide on. Needs ``langchain-core``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .agent_tools import TOOLS, MetisToolbox


def metis_tools(client: Any, workspace: str) -> list[Any]:
    """The Metis tools as LangChain ``StructuredTool`` objects."""
    from langchain_core.tools import StructuredTool

    toolbox = MetisToolbox(client, workspace)

    def make(spec: dict[str, Any]) -> Any:
        name = spec["name"]

        def run(**kwargs: Any) -> dict[str, Any]:
            return toolbox.call(name, kwargs)

        return StructuredTool.from_function(func=run, name=name, description=spec["description"],
                                            args_schema=spec["parameters"],
                                            handle_tool_error=True)

    return [make(spec) for spec in TOOLS]


def _retriever_class() -> type:
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever
    from pydantic import ConfigDict

    class _MetisRetriever(BaseRetriever):
        """Governed guidance for the situation ``context_provider`` (or ``context``) describes.
        The query text is ignored: the gate decides from the recorded conditions."""

        model_config = ConfigDict(arbitrary_types_allowed=True)

        client: Any
        workspace: str
        context: dict[str, Any] | None = None
        context_provider: Callable[[], dict[str, Any]] | None = None
        role: str | None = None

        def _get_relevant_documents(self, query: str, *, run_manager: Any = None) -> list[Any]:
            situation = self.context_provider() if self.context_provider else dict(self.context or {})
            result = self.client.retrieve(self.workspace, situation, role=self.role)
            actions = result.get("required_human_actions") or []
            if actions:
                return [Document(page_content=action, metadata={
                    "type": "required_human_action", "workspace": self.workspace,
                    "escalation_task_id": result.get("escalation_task_id")}) for action in actions]
            return [Document(page_content=item["guidance"], metadata={
                "type": "guidance", "workspace": self.workspace,
                "fragment_id": item["fragment_id"], "memory_id": item.get("memory_id"),
                "authority_layer": item.get("authority_layer"),
                "use_constraints": item.get("use_constraints") or [],
                "confidence": item.get("confidence")}) for item in result.get("guidance", [])]

    return _MetisRetriever


_RETRIEVER: type | None = None


def __getattr__(name: str) -> Any:
    """``MetisRetriever`` is built on first use, so importing this module needs no LangChain."""
    global _RETRIEVER
    if name == "MetisRetriever":
        if _RETRIEVER is None:
            _RETRIEVER = _retriever_class()
        return _RETRIEVER
    raise AttributeError(name)
