from __future__ import annotations

import typer

from ...resources import repo_root
from ...scenarios import SCENARIOS
from ..state import evidence_path, save_state


def demo(
    scenario: str = typer.Argument("manufacturing-pump-vibration", help="Scenario to run."),
    live_model: bool = typer.Option(False, "--live-model", help="Use a live local Gemma model if available."),
    open_ui: bool = typer.Option(False, "--open", "-o", help="Open the interactive demo (docs/demo.html) in a browser."),
) -> None:
    """Run an end-to-end Metis demo locally (no cloud APIs)."""
    if scenario not in SCENARIOS:
        raise typer.BadParameter(f"Unknown scenario. Choose from: {', '.join(SCENARIOS)}")
    runner = SCENARIOS[scenario]
    run = runner(use_live_model=live_model)
    typer.echo(f"\n=== Metis demo: {scenario} ===\n")
    for label, detail in (run.steps or [("Completed.", run.fragment.fragment_id if run.fragment else "")]):
        typer.echo(f"{label}\n    {detail}")
    save_state(run.engine, scenario=scenario)
    vr = run.engine.verify()
    typer.echo(f"\nEvidence chain verified: {vr.ok} ({vr.checked} entries)")
    typer.echo(f"Audit exported: {evidence_path()}")
    typer.echo("Tacit memory is governed, situated guidance, not ground truth. See ETHICAL_USE.md.")

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
