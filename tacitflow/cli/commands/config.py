from __future__ import annotations

import typer

from ...models.model_config import load_model_config, set_model_key

config_app = typer.Typer(help="Configure TacitFlow (local model runtime, etc.).")


@config_app.command("set")
def config_set(key: str = typer.Argument(...), value: str = typer.Argument(...)) -> None:
    """e.g. `tacitflow config set model.provider ollama`."""
    try:
        set_model_key(key, value)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Set {key} = {value}")


@config_app.command("show")
def config_show() -> None:
    typer.echo(load_model_config().model_dump_json(indent=2))
