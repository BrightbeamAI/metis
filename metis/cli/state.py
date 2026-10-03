"""Shared helpers for CLI commands: the local project, runtime contexts, and scenario runs."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from ..conditions.context import TacitContext
from ..engine import MetisEngine
from ..project import NoWorkspace, Project, WorkspaceBusy
from ..scenarios import SPECS, DemoRun, run_spec


def project() -> Project:
    return Project()


def load_context(path: str) -> TacitContext:
    return TacitContext.model_validate(json.loads(Path(path).read_text()))


def load_state(workspace: str | None = None) -> dict:
    try:
        return project().load_state(workspace)
    except NoWorkspace as exc:
        raise typer.BadParameter(str(exc)) from exc


def open_engine(workspace: str | None = None, *, read_only: bool = False) -> tuple[Project, MetisEngine]:
    proj = project()
    try:
        return proj, proj.open(workspace, read_only=read_only)
    except (NoWorkspace, WorkspaceBusy) as exc:
        raise typer.BadParameter(str(exc)) from exc


def run_scenario(scenario: str, *, live_model: bool = False) -> tuple[Project, DemoRun]:
    """Run a synthetic scenario into its own new workspace in the local project."""
    if scenario not in SPECS:
        raise typer.BadParameter(f"Unknown scenario. Choose from: {', '.join(SPECS)}")
    spec = SPECS[scenario]
    proj = project()
    workspace_id = proj.unique_workspace_id(spec.workspace_id)
    engine = proj.create_engine(workspace_id, name=spec.name, site=spec.site,
                                use_live_model=live_model)
    run = run_spec(spec, engine=engine)
    proj.save(engine)
    return proj, run
