"""Metis, a reference toolkit for governed tacit fragment capture.

Metis captures situated human practice as partial, validated, context-bound fragments
tied to provenance, consent, authority, review state, and retrieval constraints, and turns
validated fragments into governed tacit memory objects that AI agents can use alongside
procedural, semantic, and episodic memory, exposed only through condition-aware governance
gates. It uses local Ollama/Gemma models for bounded assistance and CHAP as its protocol
foundation.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .engine import MetisEngine

__all__ = ["MetisEngine", "__version__"]
