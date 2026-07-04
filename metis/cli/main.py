"""Metis command-line interface (Metis-first).

    metis init
    metis demo manufacturing-pump-vibration
    metis workspace describe
    metis fragment list | show <id>
    metis memory list | show <id> | query --context <file>
    metis capture --example manufacturing-pump-vibration
    metis retrieve --context <file>
    metis audit read | export --out evidence.jsonl
    metis model check | pull gemma4 | run --prompt "..."
    metis config set model.provider ollama
"""
from __future__ import annotations

import typer

from .commands.audit import audit_app
from .commands.capture import capture
from .commands.config import config_app
from .commands.demo import demo
from .commands.fragment import fragment_app
from .commands.init import init
from .commands.memory import memory_app
from .commands.model import model_app
from .commands.retrieve import retrieve
from .commands.workspace import workspace_app

app = typer.Typer(
    help="Metis, a CHAP-aligned, local-first toolkit for governed tacit fragment capture.",
    no_args_is_help=True,
    add_completion=False,
)

app.command()(init)
app.command()(demo)
app.command()(capture)
app.command()(retrieve)
app.add_typer(workspace_app, name="workspace")
app.add_typer(fragment_app, name="fragment")
app.add_typer(memory_app, name="memory")
app.add_typer(audit_app, name="audit")
app.add_typer(model_app, name="model")
app.add_typer(config_app, name="config")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
