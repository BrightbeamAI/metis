from __future__ import annotations

import shutil
import subprocess

import typer

from ...models.model_config import load_model_config
from ...models.ollama_client import OllamaClient

model_app = typer.Typer(help="Local model (Ollama / Gemma) commands. Local-only by design.")


@model_app.command("check")
def model_check() -> None:
    """Check that a local Ollama runtime is reachable and the configured model is present."""
    cfg = load_model_config()
    client = OllamaClient(cfg, deterministic=False)
    up = client.available()
    typer.echo(f"provider={cfg.provider} model={cfg.name} url={cfg.url}")
    if up:
        present = client.model_available()
        typer.echo(f"Ollama reachable: yes | model '{cfg.name}' available: {present}")
        if not present:
            typer.echo(f"Pull it with: ollama pull {cfg.name}")
    else:
        typer.echo("Ollama not reachable. Metis will use deterministic fixtures.")
        typer.echo("Install from https://ollama.com and run `ollama serve`, then `metis model pull gemma4`.")


@model_app.command("pull")
def model_pull(name: str = typer.Argument("gemma4")) -> None:
    """Pull a local model via Ollama (falls back to printed instructions)."""
    if shutil.which("ollama"):
        typer.echo(f"Running: ollama pull {name}")
        try:
            subprocess.run(["ollama", "pull", name], check=True)
            return
        except Exception as exc:  # pragma: no cover
            typer.echo(f"ollama pull failed: {exc}")
    typer.echo(f"Ollama CLI not found. Install Ollama, then run: ollama pull {name}")


@model_app.command("run")
def model_run(
    prompt: str = typer.Option(..., "--prompt", help="Prompt for a bounded, assistive model call."),
    purpose: str = typer.Option("draft_whisper", "--purpose"),
) -> None:
    """Run a single bounded model call. Output is an advisory draft only."""
    cfg = load_model_config()
    client = OllamaClient(cfg, deterministic=False)
    res = client.run(purpose, prompt)
    mode = "live Gemma" if res.used_live_model else "deterministic fixture"
    typer.echo(f"[{mode}] {res.text}")
    typer.echo("Note: model output is an advisory draft, never a governance decision.")
