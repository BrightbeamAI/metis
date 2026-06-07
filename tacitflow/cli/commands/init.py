from __future__ import annotations

import typer

from ...models.model_config import ModelConfig, config_path, project_home, save_model_config


def init(
    home: str = typer.Option(None, help="Project home (defaults to ./.tacitflow or $TACITFLOW_HOME)."),
) -> None:
    """Initialise a local TacitFlow project (config + storage)."""
    base = project_home(home)
    base.mkdir(parents=True, exist_ok=True)
    if not config_path(home).exists():
        save_model_config(ModelConfig(), home)
    try:
        from ...storage.sqlite_store import SqliteStore
        SqliteStore(base / "tacitflow.db").close()
    except Exception:
        pass
    typer.echo(f"Initialised TacitFlow project at {base}")
    typer.echo(f"  config: {config_path(home)}")
    typer.echo("  default model: ollama / gemma4 (local). Run `tacitflow model check`.")
