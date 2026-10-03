from __future__ import annotations

import json

import typer

from ..state import load_state

fragment_app = typer.Typer(help="Inspect captured tacit fragments.")

_WORKSPACE = typer.Option(None, "--workspace", help="Workspace (default: the active one).")


@fragment_app.command("list")
def fragment_list(workspace: str = _WORKSPACE) -> None:
    frags = load_state(workspace).get("fragments", [])
    if not frags:
        typer.echo("No fragments.")
        return
    for f in frags:
        typer.echo(f"{f['fragment_id']:>10}  {f['category']:<22} "
                   f"layer={f['authority_layer']:<10} state={f['validation_state']:<22} "
                   f"revocation={f['revocation_status']}")


@fragment_app.command("show")
def fragment_show(fragment_id: str = typer.Argument(...), workspace: str = _WORKSPACE) -> None:
    for f in load_state(workspace).get("fragments", []):
        if f["fragment_id"] == fragment_id:
            typer.echo(json.dumps(f, indent=2))
            return
    raise typer.BadParameter(f"Unknown fragment: {fragment_id}")
