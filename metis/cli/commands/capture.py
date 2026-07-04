from __future__ import annotations

import typer

from ...scenarios import SCENARIOS
from ..state import save_state


def capture(
    example: str = typer.Option("manufacturing-pump-vibration", "--example", help="Synthetic example to capture."),
) -> None:
    """Run the capture loop for a synthetic example and store the resulting fragment."""
    if example not in SCENARIOS:
        raise typer.BadParameter(f"Unknown example. Choose from: {', '.join(SCENARIOS)}")
    run = SCENARIOS[example]()
    save_state(run.engine, scenario=example)
    f = run.fragment
    typer.echo(f"Captured fragment {f.fragment_id} [{f.category.value}] "
               f"-> authority={f.authority_layer.value}, state={f.validation_state.value}")
    if run.memory:
        typer.echo(f"Promoted to tacit memory object {run.memory.memory_id} "
                   f"(visibility={run.memory.agent_visibility.value}).")
