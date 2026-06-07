from __future__ import annotations

import json

import typer

from ..state import load_state

fragment_app = typer.Typer(help="Inspect captured tacit fragments.")


@fragment_app.command("list")
def fragment_list() -> None:
    state = load_state()
    frags = state.get("fragments", [])
    if not frags:
        typer.echo("No fragments.")
        return
    for f in frags:
        typer.echo(f"{f['fragment_id']:>10}  {f['category']:<22} "
                   f"layer={f['authority_layer']:<10} state={f['validation_state']:<22} "
                   f"revocation={f['revocation_status']}")


@fragment_app.command("show")
def fragment_show(fragment_id: str = typer.Argument(...)) -> None:
    state = load_state()
    for f in state.get("fragments", []):
        if f["fragment_id"] == fragment_id:
            typer.echo(json.dumps(f, indent=2))
            return
    raise typer.BadParameter(f"Unknown fragment: {fragment_id}")
