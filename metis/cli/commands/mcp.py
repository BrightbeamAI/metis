from __future__ import annotations

import importlib.util

import typer


def mcp(
    workspace: str = typer.Option(None, "--workspace", help="Workspace to serve (default: the active one)."),
    seed_demo: bool = typer.Option(True, "--seed-demo/--no-seed-demo",
                                   help="Seed the pump demo when the project has no workspace."),
) -> None:
    """Serve this project's governed tacit memory to MCP clients over stdio."""
    if importlib.util.find_spec("mcp") is None:
        typer.secho('The MCP server needs the optional extra: pip install "metis-memory[mcp]"', err=True)
        raise typer.Exit(code=1)
    from ...mcp.server import serve
    from ...project import NoWorkspace, WorkspaceBusy

    try:
        serve(workspace=workspace, seed_demo=seed_demo)
    except (NoWorkspace, WorkspaceBusy) as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(code=1) from exc
