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
outbox_cmds = typer.Typer(help="Inspect and deliver queued notifications.", no_args_is_help=True)
server_app.add_typer(workspace_cmds, name="workspace")
server_app.add_typer(member_cmds, name="member")
server_app.add_typer(key_cmds, name="api-key")
server_app.add_typer(outbox_cmds, name="outbox")

CLI_ACTOR = "service:metis-cli"


def _need_server_extra() -> None:
    missing = [m for m in ("fastapi", "uvicorn", "sqlalchemy", "jwt")
               if importlib.util.find_spec(m) is None]
    if missing:
        typer.secho('The server needs the optional extra: pip install "metis-memory[server]"',
                    err=True)
        raise typer.Exit(code=1)


def _repository(*, migrate: bool | None = None):
    """The server's repository, with the same notification channels as the server."""
    _need_server_extra()
    from ...server.factory import build_repository
    from ...server.settings import ServerSettings

    return build_repository(ServerSettings.from_env(), migrate=migrate)


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
    """Create or upgrade the database schema. Run it as the role that owns the tables, for
    example from a pre-upgrade job, when servers run with METIS_MIGRATE_ON_START=false."""
    version = _repository(migrate=True).migrate()
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
    global_role: list[str] = typer.Option([], "--global-role",
                                          help="admin (people), auditor, or metrics."),
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


@server_app.command("forget-chat-identity")
def forget_chat_identity(
    participant: str = typer.Option(..., help="The person, for example human:ana@example.com."),
    platform: str = typer.Option("teams", help="The chat tool."),
) -> None:
    """Forget where Metis reaches a person in a chat tool, so the next account they install the
    app from is bound to them."""
    forgotten = _repository().forget_chat_identity(platform, participant=participant)
    typer.echo(f"forgot {forgotten} identity for {participant} in {platform}")


@server_app.command("status")
def status_cmd() -> None:
    """What an operator watches: schema version, workspaces, and notifications by status."""
    repo = _repository(migrate=False)
    typer.echo(json.dumps({"schema_version": repo.check_schema(), "workspaces": len(repo.list()),
                           "outbox": repo.outbox_counts(),
                           "oldest_pending_notification": repo.outbox_oldest_pending()}))


@server_app.command("sweep")
def sweep_cmd() -> None:
    """Lapse whispers past their deadline and queue review-date notices, once. Run it from a
    scheduler when the server's own sweep is off (METIS_SWEEP_INTERVAL_SECONDS=0)."""
    from ...server.background import sweep
    from ...server.settings import ServerSettings

    days = ServerSettings.from_env().outbox_retention_days
    typer.echo(json.dumps(sweep(_repository(), retention_days=days)))


@outbox_cmds.command("list")
def outbox_list(
    status: str = typer.Option(None, help="pending, sending, delivered, or failed."),
    limit: int = typer.Option(50, help="How many rows, newest first."),
) -> None:
    """List queued notifications."""
    for row in _repository().outbox(status=status, limit=limit):
        error = f"  error: {row['last_error']}" if row["last_error"] else ""
        typer.echo(f"{row['id']}  {row['status']:<9} {row['event']:<20} {row['channel']}"
                   f"{'  to ' + row['recipient'] if row['recipient'] else ''}"
                   f"  attempts={row['attempts']}{error}")


@outbox_cmds.command("retry")
def outbox_retry(
    row: list[int] = typer.Option([], "--id", help="A failed row to send again; all if none."),
) -> None:
    """Send failed notifications again, from the first attempt."""
    from ...notify import retry_failed

    typer.echo(f"requeued {retry_failed(_repository(), row or None)}")


@outbox_cmds.command("deliver")
def outbox_deliver() -> None:
    """Deliver every notification that is due, once."""
    from ...notify import Dispatcher

    repo = _repository()
    if repo.notifier is None:
        typer.secho("No notification channels are configured.", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(Dispatcher(repo, repo.notifier.channels).run_once()))
