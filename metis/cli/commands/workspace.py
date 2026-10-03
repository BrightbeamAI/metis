from __future__ import annotations

import json

import typer

from ...project import NoWorkspace
from ..state import load_state, project

workspace_app = typer.Typer(help="List, select, and describe workspaces in the local project.")


@workspace_app.command("list")
def workspace_list() -> None:
    proj = project()
    active = proj.active_workspace()
    ids = proj.workspace_ids()
    if not ids:
        typer.echo(f"No workspaces in {proj.home}.")
        return
    for workspace_id in ids:
        typer.echo(f"{'*' if workspace_id == active else ' '} {workspace_id}")


@workspace_app.command("use")
def workspace_use(workspace_id: str = typer.Argument(...)) -> None:
    try:
        project().set_active(workspace_id)
    except NoWorkspace as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Active workspace: {workspace_id}")


@workspace_app.command("describe")
def workspace_describe(workspace: str = typer.Option(None, "--workspace")) -> None:
    typer.echo(json.dumps(load_state(workspace).get("workspace", {}), indent=2))
