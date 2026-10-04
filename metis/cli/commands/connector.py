"""``metis connector``: check source mappings and import records from workplace systems."""
from __future__ import annotations

import json
import os

import typer

connector_app = typer.Typer(help="Map and import records from workplace systems.",
                            no_args_is_help=True)


def _mapping(source: str, mappings: str | None):
    from ...connectors.mapping import load_mappings

    path = mappings or os.environ.get("METIS_CONNECTORS_FILE")
    if not path:
        typer.secho("Name the mappings file with --mappings or METIS_CONNECTORS_FILE.", err=True)
        raise typer.Exit(code=1)
    found = load_mappings(path)
    if source not in found:
        typer.secho(f"No source {source!r} in {path}; it has {', '.join(sorted(found)) or 'none'}.",
                    err=True)
        raise typer.Exit(code=1)
    return found[source]


@connector_app.command("check")
def check(
    source: str = typer.Option(..., help="The source mapping to use."),
    file: str = typer.Option(..., help="Records as JSON, JSON Lines, or CSV."),
    mappings: str = typer.Option(None, help="The mappings file (default: METIS_CONNECTORS_FILE)."),
) -> None:
    """Show what a file's records map to, without capturing anything."""
    from ...connectors.mapping import map_records, read_payload

    mapping = _mapping(source, mappings)
    records = mapping.records_in(read_payload(file))
    mapped, failed = map_records(mapping, records)
    typer.echo(json.dumps({"records": len(records), "observations": [m.as_request() for m in mapped],
                           "failed": failed,
                           "filtered": len(records) - len(mapped) - len(failed)}, indent=2))


@connector_app.command("import")
def import_records(
    workspace: str = typer.Option(..., help="The workspace to capture into."),
    source: str = typer.Option(..., help="The source mapping to use."),
    file: str = typer.Option(..., help="Records as JSON, JSON Lines, or CSV."),
    server: str = typer.Option(None, help="A Metis server URL; records go to its ingest endpoint."),
    api_key: str = typer.Option(None, envvar="METIS_API_KEY", help="The capture source's API key."),
    as_: str = typer.Option(None, "--as", help="Without --server: the capture source to act as."),
    mappings: str = typer.Option(None, help="The mappings file (needed without --server, and "
                                           "to split a file's records into batches)."),
    batch: int = typer.Option(200, help="Records per request."),
) -> None:
    """Capture observations from a file of records. The same records can be imported again:
    records already captured are reported as duplicates."""
    from ...connectors.mapping import read_payload

    payload = read_payload(file)
    totals = {"records": 0, "accepted": 0, "duplicates": 0, "filtered": 0, "failed": []}
    if server:
        from ...client import MetisClient

        if not api_key:
            typer.secho("Give the capture source's API key with --api-key or METIS_API_KEY.", err=True)
            raise typer.Exit(code=1)
        client = MetisClient(server, api_key=api_key)
        send = lambda chunk: client.ingest(workspace, source, chunk)  # noqa: E731
    else:
        if not as_:
            typer.secho("Without --server, name the capture source to act as with --as.", err=True)
            raise typer.Exit(code=1)
        from ...identity import Principal
        from ...server import operations as ops
        from .server import _repository

        mapping, repo = _mapping(source, mappings), _repository()
        principal = Principal(uri=as_, subject="cli", method="cli")
        send = lambda chunk: ops.ingest(repo, principal, workspace, mapping, chunk)  # noqa: E731
    local = mappings or os.environ.get("METIS_CONNECTORS_FILE")
    if server and not isinstance(payload, list) and not local:
        chunks: list = [payload]  # the server finds the records with the source's mapping
    else:  # split into requests of --batch records
        records = payload if isinstance(payload, list) else _mapping(source, mappings).records_in(payload)
        chunks = [records[i:i + max(1, batch)] for i in range(0, len(records), max(1, batch))]
    for chunk in chunks:
        result = send(chunk)
        totals["records"] += result["records"]
        totals["accepted"] += len(result["accepted"])
        totals["duplicates"] += len(result["duplicates"])
        totals["filtered"] += result["filtered"]
        totals["failed"].extend(result["failed"])
    typer.echo(json.dumps(totals, indent=2))
