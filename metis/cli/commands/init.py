from __future__ import annotations

import typer

from ...models.model_config import ModelConfig, config_path, project_home, save_model_config
from ...project import Project


def init(
    home: str = typer.Option(None, help="Project home (defaults to ./.metis or $METIS_HOME)."),
) -> None:
    """Initialise a local Metis project: config, the CHAP store, and the workspaces directory."""
    base = project_home(home)
    Project(base).init()
    if not config_path(home).exists():
        save_model_config(ModelConfig(), home)
    typer.echo(f"Initialised Metis project at {base}")
    typer.echo(f"  config: {config_path(home)}")
    typer.echo(f"  CHAP store: {base / 'chap.db'}")
    typer.echo("  default model: ollama / gemma4 (local). Run `metis model check`.")
