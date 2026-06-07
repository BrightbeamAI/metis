"""The AgentMemoryContext an agent receives at runtime.

It deliberately keeps the four memory types distinct:
  * procedural, what is formally prescribed,
  * semantic , general facts and concepts,
  * episodic , past cases and events,
  * tacit    , validated situated guidance under explicit constraints (gate-only).
Blocked tacit results appear with reasons in the audit trail but never as usable guidance.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)


class TacitMemoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    fragment_id: str
    authority_layer: str
    content: str
    use_constraints: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    audit_refs: list[int] = Field(default_factory=list)


class BlockedTacitMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fragment_id: str | None = None
    memory_id: str | None = None
    reason: str
    detail: str | None = None


class AgentMemoryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    procedural_memory: list[MemoryEntry] = Field(default_factory=list)
    semantic_memory: list[MemoryEntry] = Field(default_factory=list)
    episodic_memory: list[MemoryEntry] = Field(default_factory=list)
    tacit_memory: list[TacitMemoryEntry] = Field(default_factory=list)
    blocked_tacit_memory: list[BlockedTacitMemory] = Field(default_factory=list)
    governance_notes: list[str] = Field(default_factory=list)
    required_human_actions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    audit_refs: list[int] = Field(default_factory=list)
