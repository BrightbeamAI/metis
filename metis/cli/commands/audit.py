from __future__ import annotations

import json
import shutil

import typer

from ...audit.replay import replay
from ..state import open_engine, project

audit_app = typer.Typer(help="Read, verify, and export a workspace's CHAP evidence chain.")

_WORKSPACE = typer.Option(None, "--workspace", help="Workspace (default: the active one).")


def _ledger(workspace: str | None):
    proj = project()
    workspace = workspace or proj.active_workspace()
    path = proj.ledger_path(workspace) if workspace else None
    if path is None or not path.exists():
        raise typer.BadParameter("No evidence ledger. Run a demo or capture first.")
    return path


@audit_app.command("read")
def audit_read(limit: int = typer.Option(40, "--limit"), workspace: str = _WORKSPACE) -> None:
    path = _ledger(workspace)
    result = replay(path)
    typer.echo(f"Evidence entries: {result.checked} | chain verified: {result.ok}")
    for e in result.errors:
        typer.echo(f"  ERROR: {e}")
    for line in path.read_text().splitlines()[:limit]:
        rec = json.loads(line)
        typer.echo(f"  seq={rec['seq']:>3} {rec['method_or_type']:<22} from={rec['from']}")


@audit_app.command("verify")
def audit_verify(workspace: str = _WORKSPACE) -> None:
    """Verify the chain in the CHAP store and the ledger, and check that they agree."""
    path = _ledger(workspace)
    ledger = replay(path)
    _, engine = open_engine(workspace)  # opening checks the ledger against the store
    stored = engine.verify()
    typer.echo(f"CHAP store: {stored.checked} entries, verified={stored.ok}")
    typer.echo(f"Ledger:     {ledger.checked} entries, verified={ledger.ok}")
    agree = stored.checked == ledger.checked
    typer.echo(f"Store and ledger agree: {agree}")
    if not (stored.ok and ledger.ok and agree):
        raise typer.Exit(code=1)


@audit_app.command("export")
def audit_export(out: str = typer.Option("evidence.jsonl", "--out"), workspace: str = _WORKSPACE) -> None:
    shutil.copyfile(_ledger(workspace), out)
    typer.echo(f"Exported audit chain to {out}")
