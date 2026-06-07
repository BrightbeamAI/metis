from __future__ import annotations

import typer

from ...retrieval.explain import explain
from ..state import load_context, load_state, rebuild_fragment_store, rebuild_tacit_store


def retrieve(
    context: str = typer.Option(..., "--context", help="Path to a JSON runtime context."),
    role: str = typer.Option(None, "--role", help="Requesting role."),
) -> None:
    """Run the condition-aware retrieval gate against a runtime context (not semantic search)."""
    from ...retrieval.gate import RetrievalGate

    state = load_state()
    fs = rebuild_fragment_store(state)
    ts = rebuild_tacit_store(state)
    ctx = load_context(context)
    ids = {m.fragment_id: m.memory_id for m in ts.all()}
    decision = RetrievalGate().retrieve(fs.all(), ctx, role=role, memory_ids=ids)
    typer.echo(explain(decision))
