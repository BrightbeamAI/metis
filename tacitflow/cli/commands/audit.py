from __future__ import annotations

import shutil

import typer

from ...audit.replay import replay
from ..state import evidence_path, load_state  # noqa: F401

audit_app = typer.Typer(help="Read, verify, and export the CHAP-compatible audit chain.")


@audit_app.command("read")
def audit_read(limit: int = typer.Option(40, "--limit")) -> None:
    path = evidence_path()
    if not path.exists():
        raise typer.BadParameter("No audit chain. Run a demo or capture first.")
    result = replay(path)
    typer.echo(f"Evidence entries: {result.checked} | chain verified: {result.ok}")
    if result.errors:
        for e in result.errors:
            typer.echo(f"  ERROR: {e}")
    import json
    for line in path.read_text().splitlines()[:limit]:
        rec = json.loads(line)
        typer.echo(f"  seq={rec['seq']:>3} {rec['method_or_type']:<22} from={rec['from']}")


@audit_app.command("export")
def audit_export(out: str = typer.Option("evidence.jsonl", "--out")) -> None:
    src = evidence_path()
    if not src.exists():
        raise typer.BadParameter("No audit chain to export. Run a demo or capture first.")
    shutil.copyfile(src, out)
    typer.echo(f"Exported audit chain to {out}")
