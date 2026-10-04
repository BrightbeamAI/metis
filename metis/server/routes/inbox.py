"""The caller's inbox across workspaces, and the web app that shows it."""
from __future__ import annotations

import base64
import datetime as _dt
import functools
import hashlib
import re
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from ... import __version__
from ...governance.membership import Role
from ...identity import Principal
from ..access import contributed
from ..deps import principal, repository, settings
from .fragments import review_items

router = APIRouter(tags=["inbox"])


def _deadline(engine: Any, whisper_id: str) -> str | None:
    ws = engine.adapter.coord.get_workspace(engine.adapter.workspace_id)
    prompt = ws.whispers.get(whisper_id) if ws else None
    if prompt is None:
        return None
    asked = _dt.datetime.fromisoformat(prompt.asked_at.replace("Z", "+00:00"))
    return (asked + _dt.timedelta(milliseconds=prompt.deadline_ms)).isoformat()


def _collect(engine: Any, p: Principal, roles: set[str]) -> dict[str, list[dict[str, Any]]]:
    where = {"id": engine.adapter.workspace_id, "name": engine.adapter.name}
    out: dict[str, list[dict[str, Any]]] = {"whispers": [], "reviews": [], "escalations": [],
                                            "contributions": []}
    if Role.worker.value in roles:
        for pending in engine.pending_captures.values():
            if pending.worker != p.uri or pending.deferred or pending.whisper is None:
                continue
            prompt = engine.adapter.artefacts.get(pending.whisper_id) or {}
            out["whispers"].append({
                "workspace": where, "whisper_id": pending.whisper_id,
                "question": pending.whisper.question,
                "options": [o["id"] for o in pending.whisper.options],
                "observation": pending.observation.work_as_done or pending.observation.text,
                "work_as_imagined": pending.observation.work_as_imagined,
                "candidate": {"category": pending.candidate.category,
                              "hypothesis": pending.candidate.hypothesis},
                "asked_at": prompt.get("produced_at"),
                "deadline_at": _deadline(engine, pending.whisper_id)})
    if Role.reviewer.value in roles:
        for item in review_items(engine, p, with_fragment=True):
            if item["your_approval"] is None:
                out["reviews"].append({"workspace": where, **item})
    if Role.escalation.value in roles:
        out["escalations"] = [{"workspace": where, **t} for t in engine.escalation_tasks()]
    for frag in engine.fragments.all():
        if contributed(frag, p.uri):
            out["contributions"].append({
                "workspace": where, "fragment_id": frag.fragment_id, "title": frag.title,
                "content": frag.content, "category": frag.category.value,
                "validation_state": frag.validation_state.value,
                "authority_layer": frag.authority_layer.value,
                "revocation_status": frag.revocation_status.value,
                "consent": frag.consent.consent_status.value,
                "review_open": engine.governance.review_open(frag.fragment_id)})
    return out


@router.get("/v1/me/inbox", summary="What awaits the caller, across their workspaces")
def inbox(p: Principal = Depends(principal), repo: Any = Depends(repository)) -> dict[str, Any]:
    """Whispers to answer, reviews awaiting the caller's vote, open escalations to decide, and
    the fragments the caller contributed."""
    combined: dict[str, list[dict[str, Any]]] = {"whispers": [], "reviews": [],
                                                 "escalations": [], "contributions": []}
    for workspace_id, roles in repo.memberships(p.uri).items():
        part = repo.read(workspace_id, lambda e, r=set(roles): _collect(e, p, r))
        for key, items in part.items():
            combined[key].extend(items)
    return {"uri": p.uri, "display_name": p.display_name, **combined}


@functools.lru_cache(maxsize=1)
def _app_page() -> tuple[str, str]:
    """The web app, and the hashes of its inline scripts for the Content-Security-Policy."""
    html = resources.files("metis.server").joinpath("static/app.html").read_text(encoding="utf-8")
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
        + "'" for script in re.findall(r"<script>(.*?)</script>", html, re.S))
    return html, hashes


@router.get("/app", include_in_schema=False)
def app_page(cfg: Any = Depends(settings)) -> HTMLResponse:
    """The web app. Only its own script runs, and it talks only to this server and the
    identity provider."""
    html, hashes = _app_page()
    connect = ["'self'"]
    if cfg.oidc_issuer:
        issuer = urlparse(cfg.oidc_issuer)
        connect.append(f"{issuer.scheme}://{issuer.netloc}")
    policy = ("default-src 'none'; " f"script-src {hashes}; style-src 'self' 'unsafe-inline'; "
              f"connect-src {' '.join(connect)}; img-src 'self' data:; base-uri 'none'; "
              "form-action 'self'; frame-ancestors 'none'")
    return HTMLResponse(html, headers={"Content-Security-Policy": policy,
                                       "X-Frame-Options": "DENY"})


@router.get("/app/config", include_in_schema=False)
def app_config(cfg: Any = Depends(settings)) -> dict[str, Any]:
    """What the web app needs to sign people in. Public: it holds no secrets. The browser
    reads the provider's endpoints from the issuer's discovery document itself, so they are
    the addresses people reach."""
    oidc = None
    if cfg.oidc_issuer and cfg.ui_client_id:
        oidc = {"issuer": cfg.oidc_issuer, "client_id": cfg.ui_client_id, "scopes": cfg.ui_scopes}
    return {"version": __version__, "oidc": oidc, "api_keys": bool(cfg.api_keys_file),
            "trusted_proxy": bool(cfg.trusted_proxy_secret)}
