"""A Python client for the Metis server.

    from metis.client import MetisClient

    client = MetisClient("https://metis.example.com", api_key="metis_...")
    guidance = client.retrieve("wsp_plant_a", {"equipment_family": "centrifugal_pump",
                                                "operating_mode": "high_load"})
    for item in guidance["guidance"]:
        print(item["guidance"], item["use_constraints"])
    if guidance["required_human_actions"]:
        decision = client.wait_for_escalation("wsp_plant_a", guidance["escalation_task_id"])

Sign in with an OIDC access token (``token``, a string or a function that returns one), an API
key (``api_key``), or OAuth 2.0 client credentials (``credentials=ClientCredentials(...)``),
which fetches and renews the agent's own token. ``AsyncMetisClient`` has the same methods as
coroutines. Errors are ``MetisError`` subclasses carrying the server's status and detail.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx


class MetisError(Exception):
    """The server refused or failed a request."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class NotAuthenticated(MetisError):
    """401: missing, expired, or unknown credentials."""


class Forbidden(MetisError):
    """403: the caller's roles do not allow the action."""


class NotFound(MetisError):
    """404: no such thing, or the caller may not know it exists."""


class Conflict(MetisError):
    """409: the action conflicts with a fragment's state or an open review."""


class Invalid(MetisError):
    """422: the request's content is invalid."""


_ERRORS = {401: NotAuthenticated, 403: Forbidden, 404: NotFound, 409: Conflict, 422: Invalid}


class EscalationTimeout(TimeoutError):
    """No person decided the escalation within the time given."""


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if not isinstance(detail, str):
        detail = response.text or response.reason_phrase
    raise _ERRORS.get(response.status_code, MetisError)(response.status_code, detail)


def _seg(value: str) -> str:
    return quote(str(value), safe="")


class ClientCredentials:
    """An agent's own OAuth 2.0 token, from the client credentials grant, renewed before it
    expires."""

    def __init__(self, token_url: str, client_id: str, client_secret: str, *,
                 scope: str | None = None, audience: str | None = None, timeout: float = 10.0,
                 http: httpx.Client | None = None) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.audience = audience
        self.timeout = timeout
        self._http = http
        self._token: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def token(self) -> str:
        with self._lock:
            if self._token is None or time.monotonic() > self._expires - 30:
                form = {"grant_type": "client_credentials", "client_id": self.client_id,
                        "client_secret": self.client_secret}
                if self.scope:
                    form["scope"] = self.scope
                if self.audience:
                    form["audience"] = self.audience
                http = self._http or httpx.Client(timeout=self.timeout)
                try:
                    response = http.post(self.token_url, data=form)
                finally:
                    if self._http is None:
                        http.close()
                _raise_for(response)
                body = response.json()
                self._token = body["access_token"]
                self._expires = time.monotonic() + float(body.get("expires_in", 300))
            return self._token

    def forget(self, rejected: str | None = None) -> None:
        """Drop the token the server rejected (rotated keys, a revoked grant), so the next call
        fetches a new one."""
        with self._lock:
            if rejected is None or rejected == self._token:
                self._token, self._expires = None, 0.0


class _Endpoints:
    """The server's API as methods. Each returns whatever ``_call`` returns: a result for the
    synchronous client, a coroutine for the asynchronous one."""

    def _call(self, method: str, path: str, *, json: Any = None,
              params: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    @staticmethod
    def _ws(workspace: str) -> str:
        return f"/v1/workspaces/{_seg(workspace)}"

    # -- the caller and workspaces --
    def me(self) -> Any:
        return self._call("GET", "/v1/me")

    def inbox(self) -> Any:
        return self._call("GET", "/v1/me/inbox")

    def workspaces(self) -> Any:
        return self._call("GET", "/v1/workspaces")

    def workspace(self, workspace: str) -> Any:
        return self._call("GET", self._ws(workspace))

    def create_workspace(self, workspace: str, name: str, *, site: str = "site",
                         review_rule: str = "quorum:2", members: list[dict[str, Any]] | None = None,
                         whisper_deadline_hours: int | None = None) -> Any:
        body: dict[str, Any] = {"id": workspace, "name": name, "site": site,
                                "review_rule": review_rule, "members": members or []}
        if whisper_deadline_hours:
            body["whisper_deadline_hours"] = whisper_deadline_hours
        return self._call("POST", "/v1/workspaces", json=body)

    def members(self, workspace: str) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/members")

    def set_member(self, workspace: str, uri: str, roles: list[str], *,
                   display_name: str | None = None, reason: str | None = None) -> Any:
        return self._call("PUT", f"{self._ws(workspace)}/members", json={
            "uri": uri, "roles": roles, "display_name": display_name, "reason": reason})

    # -- capture --
    def observe(self, workspace: str, observation_id: str, work_as_done: str,
                context: dict[str, Any], *, worker: str | None = None,
                work_as_imagined: str | None = None, category: str | None = None,
                title: str | None = None, supersedes: str | None = None) -> Any:
        """Report where a worker's action differed from the procedure (capture role)."""
        return self._call("POST", f"{self._ws(workspace)}/observations", json={
            "observation_id": observation_id, "work_as_done": work_as_done, "context": context,
            "worker": worker, "work_as_imagined": work_as_imagined, "category": category,
            "title": title, "supersedes": supersedes})

    def whispers(self, workspace: str) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/whispers")

    def answer_whisper(self, workspace: str, whisper_id: str, response: str, consent: str, *,
                       corrected_text: str | None = None, free_text: str | None = None) -> Any:
        return self._call("POST", f"{self._ws(workspace)}/whispers/{_seg(whisper_id)}/answer",
                          json={"response": response, "consent": consent,
                                "corrected_text": corrected_text, "free_text": free_text})

    def ingest(self, workspace: str, source: str, payload: Any) -> Any:
        """Send records from a configured source (capture role): one record, a list, or the
        source's own payload."""
        return self._call("POST", f"{self._ws(workspace)}/ingest/{_seg(source)}", json=payload)

    # -- fragments and review --
    def fragments(self, workspace: str, *, validation_state: str | None = None,
                  authority_layer: str | None = None) -> Any:
        params = {k: v for k, v in (("validation_state", validation_state),
                                    ("authority_layer", authority_layer)) if v}
        return self._call("GET", f"{self._ws(workspace)}/fragments", params=params or None)

    def fragment(self, workspace: str, fragment_id: str) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/fragments/{_seg(fragment_id)}")

    def contest(self, workspace: str, fragment_id: str, action: str, rationale: str, *,
                proposed_correction: str | None = None) -> Any:
        return self._call("POST", f"{self._ws(workspace)}/fragments/{_seg(fragment_id)}/contest",
                          json={"action": action, "rationale": rationale,
                                "proposed_correction": proposed_correction})

    def withdraw(self, workspace: str, fragment_id: str, *, note: str | None = None) -> Any:
        return self._call("POST", f"{self._ws(workspace)}/fragments/{_seg(fragment_id)}/withdraw",
                          json={"note": note})

    def retire(self, workspace: str, fragment_id: str, *, reason: str = "retired",
               note: str | None = None) -> Any:
        return self._call("POST", f"{self._ws(workspace)}/fragments/{_seg(fragment_id)}/retire",
                          json={"reason": reason, "note": note})

    def reviews(self, workspace: str) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/reviews")

    def request_review(self, workspace: str, fragment_id: str, *, reason: str = "") -> Any:
        return self._call("POST", f"{self._ws(workspace)}/fragments/{_seg(fragment_id)}/reviews",
                          json={"reason": reason})

    def vote(self, workspace: str, fragment_id: str, outcome: str, *, summary: str = "",
             use_constraints: list[str] | None = None, change_control: dict[str, Any] | None = None,
             dimension_assessments: dict[str, str] | None = None) -> Any:
        return self._call("POST", f"{self._ws(workspace)}/fragments/{_seg(fragment_id)}/votes",
                          json={"outcome": outcome, "summary": summary,
                                "use_constraints": use_constraints,
                                "change_control": change_control,
                                "dimension_assessments": dimension_assessments})

    # -- agents --
    def retrieve(self, workspace: str, context: dict[str, Any], *, role: str | None = None) -> Any:
        """Governed guidance for a work situation (agent role)."""
        return self._call("POST", f"{self._ws(workspace)}/retrieve",
                          json={"context": context, "role": role})

    def agent_context(self, workspace: str, task: str, context: dict[str, Any], *,
                      role: str | None = None) -> Any:
        return self._call("POST", f"{self._ws(workspace)}/agent-context",
                          json={"task": task, "context": context, "role": role})

    def memory(self, workspace: str) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/memory")

    # -- escalations --
    def escalations(self, workspace: str, *, open_only: bool = True) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/escalations",
                          params={"open_only": str(open_only).lower()})

    def escalation(self, workspace: str, task_id: str) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/escalations/{_seg(task_id)}")

    def decide_escalation(self, workspace: str, task_id: str, outcome: str, rationale: str) -> Any:
        return self._call("POST", f"{self._ws(workspace)}/escalations/{_seg(task_id)}/decision",
                          json={"outcome": outcome, "rationale": rationale})

    # -- audit --
    def audit(self, workspace: str, *, offset: int = 0, limit: int = 100) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/audit",
                          params={"offset": offset, "limit": limit})

    def audit_verify(self, workspace: str) -> Any:
        return self._call("GET", f"{self._ws(workspace)}/audit/verify")


def _auth_header(token: str | Callable[[], str] | None, api_key: str | None,
                 credentials: ClientCredentials | None) -> dict[str, str]:
    if credentials is not None:
        return {"Authorization": f"Bearer {credentials.token()}"}
    if token is not None:
        return {"Authorization": f"Bearer {token() if callable(token) else token}"}
    if api_key is not None:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


class MetisClient(_Endpoints):
    """The synchronous client. Pass ``http`` to use your own ``httpx.Client``."""

    def __init__(self, base_url: str, *, token: str | Callable[[], str] | None = None,
                 api_key: str | None = None, credentials: ClientCredentials | None = None,
                 timeout: float = 30.0, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._token, self._api_key, self._credentials = token, api_key, credentials
        self._http = http or httpx.Client(timeout=timeout)
        self._own = http is None

    def _call(self, method: str, path: str, *, json: Any = None,
              params: dict[str, Any] | None = None) -> Any:
        for attempt in (1, 2):
            headers = _auth_header(self._token, self._api_key, self._credentials)
            response = self._http.request(method, self.base_url + path, json=json,
                                          params=params, headers=headers)
            # A 401 means the server processed nothing: with client credentials, fetch a new
            # token once and send the request again.
            if response.status_code == 401 and self._credentials is not None and attempt == 1:
                self._credentials.forget(headers["Authorization"].split(" ", 1)[1])
                continue
            break
        _raise_for(response)
        return response.json() if response.content else None

    def wait_for_escalation(self, workspace: str, task_id: str, *, timeout: float = 600.0,
                            interval: float = 5.0) -> dict[str, Any]:
        """Wait until a person decides an escalation; return the decision."""
        deadline = time.monotonic() + timeout
        while True:
            item = self.escalation(workspace, task_id)
            if item.get("decision"):
                return item["decision"]
            if time.monotonic() + interval > deadline:
                raise EscalationTimeout(f"No decision on {task_id} within {timeout:.0f} s.")
            time.sleep(interval)

    def close(self) -> None:
        if self._own:
            self._http.close()

    def __enter__(self) -> MetisClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncMetisClient(_Endpoints):
    """The asynchronous client: every method is a coroutine. Pass ``http`` to use your own
    ``httpx.AsyncClient``."""

    def __init__(self, base_url: str, *, token: str | Callable[[], str] | None = None,
                 api_key: str | None = None, credentials: ClientCredentials | None = None,
                 timeout: float = 30.0, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._token, self._api_key, self._credentials = token, api_key, credentials
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._own = http is None

    async def _call(self, method: str, path: str, *, json: Any = None,
                    params: dict[str, Any] | None = None) -> Any:
        for attempt in (1, 2):
            headers = (await asyncio.to_thread(_auth_header, self._token, self._api_key,
                                               self._credentials)
                       if self._credentials is not None
                       else _auth_header(self._token, self._api_key, None))
            response = await self._http.request(method, self.base_url + path, json=json,
                                                params=params, headers=headers)
            if response.status_code == 401 and self._credentials is not None and attempt == 1:
                self._credentials.forget(headers["Authorization"].split(" ", 1)[1])
                continue
            break
        _raise_for(response)
        return response.json() if response.content else None

    async def wait_for_escalation(self, workspace: str, task_id: str, *, timeout: float = 600.0,
                                  interval: float = 5.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            item = await self.escalation(workspace, task_id)
            if item.get("decision"):
                return item["decision"]
            if time.monotonic() + interval > deadline:
                raise EscalationTimeout(f"No decision on {task_id} within {timeout:.0f} s.")
            await asyncio.sleep(interval)

    async def aclose(self) -> None:
        if self._own:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncMetisClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
