from __future__ import annotations

import typer

from ...retrieval.explain import explain
from ..state import load_context, open_engine


def retrieve(
    context: str = typer.Option(..., "--context", help="Path to a JSON runtime context."),
    role: str = typer.Option(None, "--role", help="Requesting role."),
    workspace: str = typer.Option(None, "--workspace", help="Workspace (default: the active one)."),
) -> None:
    """Run the condition-aware retrieval gate and record the decision on the evidence chain."""
    proj, engine = open_engine(workspace)
    decision = engine.retrieve(load_context(context), role=role)
    proj.save(engine)
    typer.echo(explain(decision))
