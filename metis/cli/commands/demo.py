from __future__ import annotations

import typer

from ...resources import repo_root
from ..state import run_scenario


def demo(
    scenario: str = typer.Argument("manufacturing-pump-vibration", help="Scenario to run."),
    live_model: bool = typer.Option(False, "--live-model", help="Use a live local Gemma model if available."),
    open_ui: bool = typer.Option(False, "--open", "-o", help="Open the interactive demo (docs/demo.html) in a browser."),
) -> None:
    """Run an end-to-end Metis demo locally into a new workspace (no cloud APIs)."""
    proj, run = run_scenario(scenario, live_model=live_model)
    workspace_id = run.engine.adapter.workspace_id
    typer.echo(f"\n=== Metis demo: {scenario} ===\n")
    for label, detail in (run.steps or [("Completed.", run.fragment.fragment_id if run.fragment else "")]):
        typer.echo(f"{label}\n    {detail}")
    vr = run.engine.verify()
    typer.echo(f"\nEvidence chain verified: {vr.ok} ({vr.checked} entries)")
    typer.echo(f"Workspace: {workspace_id} (active)")
    typer.echo(f"Evidence ledger (append-only): {proj.ledger_path(workspace_id)}")
    typer.echo("Tacit memory is governed, situated guidance: it holds under its recorded conditions "
               "and stays open to challenge. See ETHICAL_USE.md.")

    demo_html = repo_root() / "docs" / "demo.html"
    if open_ui:
        if demo_html.exists():
            import webbrowser
            webbrowser.open(demo_html.resolve().as_uri())
            typer.echo(f"\nOpened interactive demo: {demo_html}")
        else:
            typer.echo("\nInteractive demo not found. Build it with: python scripts/build_demo.py")
    else:
        typer.echo(f"\nTip: open the interactive demo with `metis demo {scenario} --open` "
                   f"or open {demo_html} in a browser.")
