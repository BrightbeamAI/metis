from __future__ import annotations

import json

import typer

from ..state import load_context, load_state, open_engine

memory_app = typer.Typer(help="Inspect and query governed tacit memory.")

_WORKSPACE = typer.Option(None, "--workspace", help="Workspace (default: the active one).")


@memory_app.command("list")
def memory_list(workspace: str = _WORKSPACE) -> None:
    """List governed tacit memory objects."""
    objs = load_state(workspace).get("memory_objects", [])
    if not objs:
        typer.echo("No tacit memory objects.")
        return
    for m in objs:
        typer.echo(f"{m['memory_id']:>10}  fragment={m['fragment_id']:<10} "
                   f"layer={m['authority_layer']:<10} visibility={m['agent_visibility']}")


@memory_app.command("show")
def memory_show(memory_id: str = typer.Argument(...), workspace: str = _WORKSPACE) -> None:
    """Print one tacit memory object as JSON."""
    for m in load_state(workspace).get("memory_objects", []):
        if m["memory_id"] == memory_id:
            typer.echo(json.dumps(m, indent=2))
            return
    raise typer.BadParameter(f"Unknown memory object: {memory_id}")


@memory_app.command("query")
def memory_query(
    context: str = typer.Option(..., "--context", help="Path to a JSON runtime context."),
    role: str = typer.Option(None, "--role"),
    task_id: str = typer.Option("tsk_cli_query", "--task-id"),
    workspace: str = _WORKSPACE,
) -> None:
    """Assemble an agent memory context; tacit memory passes the gate and the query is recorded."""
    proj, engine = open_engine(workspace)
    amc = engine.agent_context(task_id, load_context(context), role=role)
    proj.save(engine)
    typer.echo(f"procedural={len(amc.procedural_memory)} semantic={len(amc.semantic_memory)} "
               f"episodic={len(amc.episodic_memory)} tacit={len(amc.tacit_memory)} "
               f"blocked={len(amc.blocked_tacit_memory)}")
    for t in amc.tacit_memory:
        typer.echo(f"  TACIT {t.memory_id} [{t.authority_layer}]: {t.content}")
        for c in t.use_constraints:
            typer.echo(f"      constraint: {c}")
    for b in amc.blocked_tacit_memory:
        flag = " (a person decides)" if b.escalate else ""
        typer.echo(f"  BLOCKED {b.memory_id or b.fragment_id}: {b.reason}{flag}")
    for action in amc.required_human_actions:
        typer.echo(f"  REQUIRED HUMAN ACTION: {action}")
