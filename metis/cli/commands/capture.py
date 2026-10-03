from __future__ import annotations

import typer

from ..state import run_scenario


def capture(
    example: str = typer.Option("manufacturing-pump-vibration", "--example", help="Synthetic example to capture."),
) -> None:
    """Run the capture loop for a synthetic example into a new workspace."""
    _, run = run_scenario(example)
    f = run.fragment
    typer.echo(f"Captured fragment {f.fragment_id} [{f.category.value}] "
               f"-> authority={f.authority_layer.value}, state={f.validation_state.value} "
               f"(workspace {run.engine.adapter.workspace_id})")
    if run.memory:
        typer.echo(f"Promoted to tacit memory object {run.memory.memory_id} "
                   f"(visibility={run.memory.agent_visibility.value}).")
