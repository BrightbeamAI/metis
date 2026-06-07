from __future__ import annotations

import json

import typer

from ..state import load_state

workspace_app = typer.Typer(help="Inspect the CHAP workspace.")


@workspace_app.command("describe")
def workspace_describe() -> None:
    state = load_state()
    typer.echo(json.dumps(state.get("workspace", {}), indent=2))
