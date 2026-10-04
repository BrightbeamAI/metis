"""``metis server``: run and administer the multi-user Metis server.

Every command reads the same ``METIS_*`` variables as the server, so ``METIS_DATABASE_URL``
points them all at one database.
"""
from __future__ import annotations

import importlib.util
import json
import os

import typer

server_app = typer.Typer(help="Run and administer the multi-user Metis server.",
                         no_args_is_help=True)
workspace_cmds = typer.Typer(help="Create and list server workspaces.", no_args_is_help=True)
member_cmds = typer.Typer(help="Manage workspace members.", no_args_is_help=True)
key_cmds = typer.Typer(help="Issue and revoke API keys.", no_args_is_help=True)
server_app.add_typer(workspace_cmds, name="workspace")
server_app.add_typer(member_cmds, name="member")
server_app.add_typer(key_cmds, name="api-key")

CLI_ACTOR = "service:metis-cli"


def _need_server_extra() -> None:
    missing = [m for m in ("fastapi", "uvicorn", "sqlalchemy", "jwt")
               if importlib.util.find_spec(m) is None]
    if missing:
        typer.secho('The server needs the optional extra: pip install "metis-memory[server]"',
                    err=True)
        raise typer.Exit(code=1)


def _repository():
    _need_server_extra()
    from ...server.settings import ServerSettings
    from ...storage.sql import SqlRepository

    return SqlRepository(ServerSettings.from_env().database_url)


def _keys_file(path: str | None) -> str:
    path = path or os.environ.get("METIS_API_KEYS_FILE")
    if not path:
        typer.secho("Name the keys file with --file or METIS_API_KEYS_FILE.", err=True)
        raise typer.Exit(code=1)
    return path


@server_app.command("run")
def run(
    host: str = typer.Option("127.0.0.1", help="Interface to listen on (0.0.0.0 in a container)."),
    port: int = typer.Option(8000, help="Port to listen on."),
    workers: int = typer.Option(1, help="Worker processes. Use 1 with SQLite."),
    log_level: str = typer.Option(None, help="Log level (default: METIS_LOG_LEVEL or info)."),
) -> None:
    """Serve the Metis API. Configure it with METIS_* environment variables."""
    _need_server_extra()
    import uvicorn

    from ...server.settings import ServerSettings

    settings = ServerSettings.from_env()
    settings.authenticator()  # refuse to start without a way to sign in
    if workers > 1 and settings.database_url.startswith("sqlite"):
        typer.secho("SQLite allows one writer: run one worker, or use PostgreSQL.", err=True)
        raise typer.Exit(code=1)
    uvicorn.run("metis.server.app:create_app", factory=True, host=host, port=port,
                workers=workers, log_level=log_level or settings.log_level,
                proxy_headers=True)


@server_app.command("migrate")
def migrate() -> None:
    """Create or upgrade the database schema."""
    version = _repository().migrate()
    typer.echo(f"schema version {version}")


@workspace_cmds.command("create")
def workspace_create(
    workspace_id: str = typer.Option(..., "--id", help="wsp_ followed by lowercase letters, digits, - or _."),
    name: str = typer.Option(..., help="A human-readable name."),
    site: str = typer.Option("site", help="The site the workspace serves."),
    review_rule: str = typer.Option("quorum:2", help="any_one_approves, all_approve, or quorum:<n>."),
    admin: list[str] = typer.Option([], "--admin", help="A participant URI to make workspace admin."),
    by: str = typer.Option(CLI_ACTOR, help="Who is recorded as creating the workspace."),
) -> None:
    """Create a workspace, optionally with its first admins."""
    from ...governance.membership import Member, Role
    from ...storage.repository import WorkspaceSettings

    settings = WorkspaceSettings(id=workspace_id, name=name, site=site, review_rule=review_rule,
                                 members=[Member(uri=u, roles=[Role.admin]) for u in admin])
    descriptor = _repository().create(settings, by=by)
    typer.echo(json.dumps({"id": descriptor["id"], "evidence_count": descriptor["evidence_count"]}))


@workspace_cmds.command("list")
def workspace_list() -> None:
    """List workspaces."""
    for w in _repository().list():
        typer.echo(f"{w.id}  {w.name}  site={w.site}  updated={w.updated_at}")


@member_cmds.command("set")
def member_set(
    workspace_id: str = typer.Option(..., "--workspace", help="The workspace id."),
    uri: str = typer.Option(..., help="The participant URI, for example human:ana@example.com."),
    roles: str = typer.Option("", help="Comma-separated roles; empty removes the member."),
    display_name: str = typer.Option(None, "--name", help="A display name."),
    reason: str = typer.Option(None, help="Why the roles change."),
    by: str = typer.Option(CLI_ACTOR, help="Who is recorded as making the change."),
) -> None:
    """Set a member's roles: worker, reviewer, agent, capture, escalation, auditor, admin."""
    wanted = [r.strip() for r in roles.split(",") if r.strip()]
    member = _repository().write(workspace_id, lambda e: e.set_member(
        uri, wanted, by=by, display_name=display_name, reason=reason))
    typer.echo(f"{uri}: " + (", ".join(r.value for r in member.roles) if member else "removed"))


@member_cmds.command("list")
def member_list(workspace_id: str = typer.Option(..., "--workspace", help="The workspace id.")) -> None:
    """List a workspace's members."""
    members = _repository().read(workspace_id, lambda e: list(e.members.values()))
    for m in members:
        typer.echo(f"{m.uri}  {', '.join(r.value for r in m.roles)}"
                   + (f"  ({m.display_name})" if m.display_name else ""))


@key_cmds.command("create")
def key_create(
    key_id: str = typer.Option(..., "--id", help="A unique name for the key."),
    uri: str = typer.Option(..., help="The participant the key signs in as, for example agent:shift-assistant."),
    display_name: str = typer.Option(None, "--name", help="A display name."),
    global_role: list[str] = typer.Option([], "--global-role", help="admin or auditor."),
    path: str = typer.Option(None, "--file", help="The keys file (default: METIS_API_KEYS_FILE)."),
) -> None:
    """Issue an API key. The key is printed once; the file keeps only its hash."""
    from ...identity import ApiKeyAuthenticator, ApiKeyEntry

    path = _keys_file(path)
    entries = ApiKeyAuthenticator.read_file(path)
    if any(e.id == key_id for e in entries):
        typer.secho(f"A key named {key_id} exists; revoke it first.", err=True)
        raise typer.Exit(code=1)
    key, digest = ApiKeyAuthenticator.generate()
    entries.append(ApiKeyEntry(id=key_id, sha256=digest, uri=uri, display_name=display_name,
                               global_roles=tuple(global_role)))
    ApiKeyAuthenticator.write_file(path, entries)
    typer.echo(key)
    typer.secho(f"Issued {key_id} for {uri}. Store the key now; it is not shown again. "
                "A running server picks it up on the next request.", err=True)


@key_cmds.command("list")
def key_list(path: str = typer.Option(None, "--file", help="The keys file.")) -> None:
    """List API keys (ids and participants, never the keys)."""
    from ...identity import ApiKeyAuthenticator

    for e in ApiKeyAuthenticator.read_file(_keys_file(path)):
        roles = f"  global: {', '.join(e.global_roles)}" if e.global_roles else ""
        typer.echo(f"{e.id}  {e.uri}{roles}")


@key_cmds.command("revoke")
def key_revoke(
    key_id: str = typer.Option(..., "--id", help="The key to revoke."),
    path: str = typer.Option(None, "--file", help="The keys file."),
) -> None:
    """Revoke an API key. A running server stops accepting it on the next request."""
    from ...identity import ApiKeyAuthenticator

    path = _keys_file(path)
    entries = ApiKeyAuthenticator.read_file(path)
    kept = [e for e in entries if e.id != key_id]
    if len(kept) == len(entries):
        typer.secho(f"No key named {key_id}.", err=True)
        raise typer.Exit(code=1)
    ApiKeyAuthenticator.write_file(path, kept)
    typer.echo(f"revoked {key_id}")
