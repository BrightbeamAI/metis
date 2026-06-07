"""TacitFlow command-line interface (TacitFlow-first).

    tacitflow init
    tacitflow demo manufacturing-pump-vibration
    tacitflow workspace describe
    tacitflow fragment list | show <id>
    tacitflow memory list | show <id> | query --context <file>
    tacitflow capture --example manufacturing-pump-vibration
    tacitflow retrieve --context <file>
    tacitflow audit read | export --out evidence.jsonl
    tacitflow model check | pull gemma4 | run --prompt "..."
    tacitflow config set model.provider ollama
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
    help="TacitFlow, a CHAP-aligned, local-first toolkit for governed tacit fragment capture.",
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
