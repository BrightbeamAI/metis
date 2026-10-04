"""Authenticators turn a request's credentials into a ``Principal``.

Each authenticator returns ``None`` when the request carries no credentials it handles, and
raises ``AuthenticationError`` when it handles the credentials and cannot accept them. An
``AuthenticatorChain`` asks each in turn.

- ``OIDCAuthenticator`` verifies a signed JWT access token from an OpenID Connect provider
  (Keycloak, Entra ID, Okta, Auth0, and others) against the provider's published keys.
- ``ApiKeyAuthenticator`` accepts API keys for agents, capture sources, and automation. Keys are
  stored only as SHA-256 hashes.
- ``TrustedHeaderAuthenticator`` accepts the identity a reverse proxy (such as oauth2-proxy)
  asserts in request headers, together with a secret only the proxy knows.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from ..integrations.chap.participants import URI_RE
from .principal import (
    AuthenticationError,
    IdentityProviderUnavailable,
    Principal,
    global_roles_allowed,
)

log = logging.getLogger("metis.identity")

API_KEY_PREFIX = "metis_"
_PARTICIPANT_TYPES = ("human", "agent", "service")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """A header value by case-insensitive name."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _bearer(headers: Mapping[str, str]) -> str | None:
    auth = _header(headers, "authorization")
    if not auth:
        return None
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _claim_path(claims: Mapping[str, Any], path: str) -> Any:
    """The claim at a dotted path, for example ``realm_access.roles``."""
    value: Any = claims
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v for v in value.replace(",", " ").split() if v]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return []


class Authenticator(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> Principal | None: ...


# ---- API keys ------------------------------------------------------------------------------
@dataclass(frozen=True)
class ApiKeyEntry:
    """One API key: its id, the SHA-256 hash of the key, and the participant it signs in as."""

    id: str
    sha256: str
    uri: str
    display_name: str | None = None
    global_roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not URI_RE.match(self.uri) or self.uri.split(":", 1)[0] not in _PARTICIPANT_TYPES:
            raise ValueError(f"API key {self.id}: invalid participant URI {self.uri!r}")
        digest = self.sha256.lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"API key {self.id}: sha256 must be 64 hexadecimal characters")
        try:
            global_roles_allowed(self.uri, self.global_roles)
        except ValueError as exc:
            raise ValueError(f"API key {self.id}: {exc}") from None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "sha256": self.sha256.lower(), "uri": self.uri}
        if self.display_name:
            data["display_name"] = self.display_name
        if self.global_roles:
            data["global_roles"] = list(self.global_roles)
        return data


class ApiKeyAuthenticator:
    """API keys, sent as ``Authorization: Bearer metis_...`` or ``X-API-Key: metis_...``.

    Built ``from_file``, the authenticator rereads the file when it changes, so keys issued or
    revoked with ``metis server api-key`` take effect without a restart. A deleted file means no
    keys; a file that cannot be parsed keeps the keys loaded before, and is logged.
    """

    _MISSING = "missing"

    def __init__(self, entries: Iterable[ApiKeyEntry], *, path: str | Path | None = None) -> None:
        self._set(list(entries))
        self.path = Path(path) if path else None
        self._digest = self._file_digest()
        self._reload_lock = threading.Lock()

    def _set(self, entries: list[ApiKeyEntry]) -> None:
        ids = [e.id for e in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("API key ids must be unique")
        self.entries = entries

    _UNREADABLE = "unreadable"

    def _file_digest(self) -> str | None:
        if self.path is None:
            return None
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return self._MISSING
        except OSError:
            return self._UNREADABLE

    def _reload_if_changed(self) -> None:
        """Reread the keys file when its contents change (it is small; the check is cheap)."""
        if self.path is None:
            return
        digest = self._file_digest()
        if digest is None or digest == self._digest:
            return
        with self._reload_lock:
            if digest == self._digest:
                return
            if digest in (self._MISSING, self._UNREADABLE):  # fail closed: a revoked key stays out
                log.error("API keys file %s is %s; no API key is accepted until it can be read",
                          self.path, "missing" if digest == self._MISSING else "unreadable")
                self._set([])
                self._digest = digest
                return
            try:
                entries = self.read_file(self.path)
                self._set(entries)
            except Exception as exc:  # keep the keys loaded before; try again on the next request
                log.error("API keys file %s cannot be read (%s); keeping the keys loaded before",
                          self.path, exc)
                return
            self._digest = digest

    @staticmethod
    def hash_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @classmethod
    def generate(cls) -> tuple[str, str]:
        """A new random key and its hash. Store the hash; give the key to its holder once."""
        key = API_KEY_PREFIX + secrets.token_urlsafe(32)
        return key, cls.hash_key(key)

    @staticmethod
    def read_file(path: str | Path) -> list[ApiKeyEntry]:
        """Entries from a YAML or JSON file with a top-level ``keys`` list."""
        path = Path(path)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(text) if text.strip() else {}
        else:
            import yaml

            data = yaml.safe_load(text) or {}
        return [ApiKeyEntry(id=str(e["id"]), sha256=str(e["sha256"]), uri=str(e["uri"]),
                            display_name=e.get("display_name"),
                            global_roles=tuple(e.get("global_roles") or ()))
                for e in data.get("keys", [])]

    @staticmethod
    def write_file(path: str | Path, entries: Iterable[ApiKeyEntry]) -> None:
        """Write the keys file in one step (a temporary file renamed over it), so a running
        server never reads half a file. A new file is readable only by its owner; a rewritten
        one keeps its permissions and owner."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"keys": [e.as_dict() for e in entries]}
        if path.suffix.lower() == ".json":
            text = json.dumps(payload, indent=2) + "\n"
        else:
            import yaml

            text = yaml.safe_dump(payload, sort_keys=False)
        try:  # the new file keeps the old one's permissions and owner, so the server reads it
            st = path.stat()
            mode, owner = st.st_mode & 0o777, (st.st_uid, st.st_gid)
        except FileNotFoundError:
            mode, owner = 0o600, None
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(tmp, mode)
            if owner is not None and hasattr(os, "chown") and owner != (os.getuid(), os.getgid()):
                try:
                    os.chown(tmp, *owner)
                except PermissionError:
                    log.warning("could not keep the owner of %s; check the server can read it",
                                path)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @classmethod
    def from_file(cls, path: str | Path) -> ApiKeyAuthenticator:
        return cls(cls.read_file(path), path=path)

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        key = _header(headers, "x-api-key")
        if key is None:
            token = _bearer(headers)
            key = token if token and token.startswith(API_KEY_PREFIX) else None
        if key is None:
            return None
        self._reload_if_changed()
        digest = self.hash_key(key.strip())
        match = None
        for entry in self.entries:  # compare every entry in constant time
            if hmac.compare_digest(entry.sha256.lower(), digest):
                match = entry
        if match is None:
            raise AuthenticationError("Unknown API key.")
        return Principal(uri=match.uri, subject=f"api-key:{match.id}", method="api_key",
                         display_name=match.display_name,
                         global_roles=frozenset(match.global_roles))


# ---- OIDC ----------------------------------------------------------------------------------
_CLIENT_CLAIMS = ("azp", "client_id", "cid", "appid")


def _client_id(claims: Mapping[str, Any]) -> str | None:
    return next((str(claims[k]) for k in _CLIENT_CLAIMS if claims.get(k)), None)


def _is_client_token(claims: Mapping[str, Any]) -> bool:
    """True for a token a client obtained for itself (client credentials), as identity
    providers mark it: Entra ID's ``idtyp`` (or an app-only token: no ``scp``, and ``oid``
    equal to ``sub``), Keycloak's service-account user for that client, Auth0's grant type and
    ``@clients`` subject, or a subject equal to the client id (Okta and others)."""
    if claims.get("idtyp") == "app" or claims.get("gty") == "client-credentials":
        return True
    client = _client_id(claims)
    username = str(claims.get("preferred_username", "")).lower()
    if client and username == f"service-account-{client.lower()}":  # Keycloak lowercases it
        return True
    sub = str(claims.get("sub", ""))
    if sub.endswith("@clients"):
        return True
    if (client and "scp" not in claims and claims.get("oid") and claims.get("oid") == sub
            and claims.get("tid")):
        return True
    clients = {str(claims[k]) for k in _CLIENT_CLAIMS if claims.get(k)}
    return bool(sub) and sub in clients


def _email_verified(value: Any) -> bool | None:
    """``email_verified`` as a boolean, or ``None`` when the token does not say."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


class OIDCAuthenticator:
    """Verify JWT access tokens issued by an OpenID Connect provider.

    The token must be signed by one of the provider's keys, carry the configured issuer and
    audience, and be unexpired. People sign in as ``human:<email>`` when the token's email is
    not marked unverified (with ``require_email_verified``, only when it is marked verified);
    otherwise as ``human:<subject>@<issuer host>``. A client signing in with its own credentials
    becomes ``agent:<client id>``. When ``participant_claim`` names a claim, an identity
    provider may set the participant URI there, of the same kind (person or client) as the
    token. Roles in ``roles_claim`` (a dotted path such as ``realm_access.roles``) grant the
    global admin and auditor roles. Keys removed from the provider's key set stop being
    accepted within ``key_cache_seconds``.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str | Sequence[str],
        jwks_url: str | None = None,
        jwks: Mapping[str, Any] | None = None,
        algorithms: Sequence[str] = ("RS256", "PS256", "ES256", "EdDSA"),
        leeway: int = 30,
        email_claim: str = "email",
        name_claim: str = "name",
        roles_claim: str = "roles",
        participant_claim: str | None = None,
        admin_role: str = "metis-admin",
        auditor_role: str = "metis-auditor",
        key_resolver: Callable[[str], Any] | None = None,
        http_timeout: float = 5.0,
        require_email_verified: bool = False,
        key_cache_seconds: int = 300,
    ) -> None:
        if not issuer:
            raise ValueError("OIDC needs an issuer")
        if not audience:
            raise ValueError("OIDC needs an audience")
        self.issuer = issuer
        self.audience = audience if isinstance(audience, str) else list(audience)
        self.jwks_url = jwks_url
        self.jwks = jwks
        self.algorithms = list(algorithms)
        self.leeway = leeway
        self.email_claim = email_claim
        self.name_claim = name_claim
        self.roles_claim = roles_claim
        self.participant_claim = participant_claim
        self.admin_role = admin_role
        self.auditor_role = auditor_role
        self.http_timeout = http_timeout
        self.require_email_verified = require_email_verified
        self.key_cache_seconds = key_cache_seconds
        self._key_resolver = key_resolver
        self._unavailable_until = 0.0
        self._resolver_lock = threading.Lock()
        self._jwk_client: Any = None

    # -- signing keys --
    def _discover_jwks_url(self) -> str:
        import httpx

        url = self.issuer.rstrip("/") + "/.well-known/openid-configuration"
        response = httpx.get(url, timeout=self.http_timeout)
        response.raise_for_status()
        return response.json()["jwks_uri"]

    def _resolver(self) -> Callable[[str], Any]:
        if self._key_resolver is not None:
            return self._key_resolver
        import jwt

        with self._resolver_lock:
            if self._key_resolver is not None:
                return self._key_resolver
            if self.jwks is not None:
                keyset = jwt.PyJWKSet.from_dict(dict(self.jwks))

                def from_set(token: str) -> Any:
                    kid = jwt.get_unverified_header(token).get("kid")
                    for key in keyset.keys:
                        if kid is None or key.key_id == kid:
                            return key.key
                    raise AuthenticationError(f"No signing key {kid!r} in the configured JWKS.")

                self._key_resolver = from_set
            else:
                # The key set is cached for key_cache_seconds and refetched after, so a key the
                # provider removes stops being accepted; individual keys are not cached longer.
                client = jwt.PyJWKClient(self.jwks_url or self._discover_jwks_url(),
                                         cache_keys=False, cache_jwk_set=True,
                                         lifespan=self.key_cache_seconds,
                                         timeout=self.http_timeout)
                self._jwk_client = client
                self._key_resolver = lambda token: client.get_signing_key_from_jwt(token).key
            return self._key_resolver

    def _key_for(self, token: str) -> Any:
        """The token's signing key. A provider that cannot be reached is reported as
        unavailable (not as a bad token) and is not asked again for a few seconds."""
        import jwt

        if time.monotonic() < self._unavailable_until:
            raise IdentityProviderUnavailable("The identity provider is unreachable; try again "
                                              "shortly.")
        try:
            return self._resolver()(token)
        except (AuthenticationError, jwt.InvalidTokenError):
            raise
        except jwt.PyJWKClientConnectionError as exc:
            cache = getattr(self._jwk_client, "jwk_set_cache", None)
            if cache is not None and cache.get() is not None:
                # The cached keys are current and hold no key for this token: refetching failed,
                # but the keys every valid token uses are at hand.
                raise AuthenticationError("The access token was signed with an unknown key.") \
                    from None
            self._unavailable_until = time.monotonic() + 5
            log.warning("identity provider keys unreachable: %s", exc)
            raise IdentityProviderUnavailable("The identity provider is unreachable; try "
                                              "again shortly.") from None
        except jwt.PyJWTError as exc:  # no key for this token in the provider's key set
            raise AuthenticationError(f"Invalid access token: {exc}") from None
        except Exception as exc:  # discovery failed: the provider is down or misconfigured
            self._unavailable_until = time.monotonic() + 5
            log.warning("identity provider discovery failed: %s", exc)
            raise IdentityProviderUnavailable("The identity provider is unreachable; try again "
                                              "shortly.") from None

    # -- authentication --
    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        token = _bearer(headers)
        if token is None or token.startswith(API_KEY_PREFIX) or token.count(".") != 2:
            return None
        import jwt

        try:
            key = self._key_for(token)
            claims = jwt.decode(token, key=key, algorithms=self.algorithms,
                                audience=self.audience, issuer=self.issuer, leeway=self.leeway,
                                options={"require": ["exp", "iss", "sub"]})
        except (AuthenticationError, IdentityProviderUnavailable):
            raise
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid access token: {exc}") from None
        return self.principal_from_claims(claims)

    def participant_uri(self, claims: Mapping[str, Any]) -> str:
        client = _is_client_token(claims)
        explicit = claims.get(self.participant_claim) if self.participant_claim else None
        if explicit is not None:
            kind = str(explicit).split(":", 1)[0]
            if not (isinstance(explicit, str) and URI_RE.match(explicit)
                    and kind in _PARTICIPANT_TYPES):
                raise AuthenticationError(f"The token's {self.participant_claim} claim is not a "
                                          "participant URI.")
            if (kind == "human") == client:
                raise AuthenticationError(f"The token's {self.participant_claim} claim names a "
                                          f"{kind} participant, but the token was issued to a "
                                          f"{'client' if client else 'person'}.")
            return explicit
        if client:
            return f"agent:{(_client_id(claims) or str(claims['sub'])).removesuffix('@clients')}"
        email = claims.get(self.email_claim)
        verified = _email_verified(claims.get("email_verified"))
        trusted = verified is True or (verified is None and not self.require_email_verified)
        if isinstance(email, str) and "@" in email and trusted:
            return f"human:{email.strip().lower()}"
        host = urlparse(self.issuer).hostname or "idp"
        return f"human:{claims['sub']}@{host}"

    def principal_from_claims(self, claims: Mapping[str, Any]) -> Principal:
        roles = set(_as_list(_claim_path(claims, self.roles_claim)))
        global_roles = set()
        if self.admin_role in roles:
            global_roles.add("admin")
        if self.auditor_role in roles:
            global_roles.add("auditor")
        uri = self.participant_uri(claims)
        if not URI_RE.match(uri):
            raise AuthenticationError(f"The token's identity is not a valid participant URI: {uri!r}")
        name = claims.get(self.name_claim) or claims.get("preferred_username")
        return Principal(uri=uri, subject=str(claims["sub"]), method="oidc",
                         display_name=str(name) if name else None, issuer=claims.get("iss"),
                         global_roles=frozenset(global_roles))


# ---- trusted proxy headers -----------------------------------------------------------------
class TrustedHeaderAuthenticator:
    """Identity asserted by a trusted reverse proxy, such as oauth2-proxy.

    The proxy authenticates the person and forwards their email and groups in headers. The
    proxy also sends a shared secret, so a request that reaches Metis without passing through
    the proxy cannot assert an identity.
    """

    def __init__(
        self,
        *,
        secret: str,
        email_header: str = "X-Forwarded-Email",
        name_header: str = "X-Forwarded-Preferred-Username",
        groups_header: str = "X-Forwarded-Groups",
        secret_header: str = "X-Metis-Proxy-Secret",
        admin_group: str = "metis-admin",
        auditor_group: str = "metis-auditor",
    ) -> None:
        if not secret:
            raise ValueError("Trusted-header sign-in needs a shared secret from the proxy")
        self.secret = secret
        self.email_header = email_header
        self.name_header = name_header
        self.groups_header = groups_header
        self.secret_header = secret_header
        self.admin_group = admin_group
        self.auditor_group = auditor_group
        self.sensitive_headers = tuple(h.lower() for h in (email_header, name_header,
                                                            groups_header, secret_header))

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        email = _header(headers, self.email_header)
        if not email:
            return None
        given = _header(headers, self.secret_header) or ""
        if not hmac.compare_digest(given.encode("utf-8"), self.secret.encode("utf-8")):
            raise AuthenticationError("The request did not come through the trusted proxy.")
        email = email.strip().lower()
        if "@" not in email or not URI_RE.match(f"human:{email}"):
            raise AuthenticationError(f"The proxy forwarded an invalid email: {email!r}")
        groups = set(_as_list(_header(headers, self.groups_header)))
        global_roles = set()
        if self.admin_group in groups:
            global_roles.add("admin")
        if self.auditor_group in groups:
            global_roles.add("auditor")
        return Principal(uri=f"human:{email}", subject=email, method="trusted_header",
                         display_name=_header(headers, self.name_header),
                         global_roles=frozenset(global_roles))


# ---- chain ---------------------------------------------------------------------------------
class AuthenticatorChain:
    """Ask each authenticator in turn; the first that recognises the credentials decides.

    ``admins`` lists participant URIs that hold the global admin role whatever their
    credentials say, so a first administrator can set up workspaces.
    """

    def __init__(self, authenticators: Iterable[Authenticator], *, admins: Iterable[str] = ()) -> None:
        self.authenticators = list(authenticators)
        self.admins = frozenset(admins)
        if not self.authenticators:
            raise ValueError("Configure at least one way to sign in")
        for uri in self.admins:
            global_roles_allowed(uri, {"admin"})
        self.sensitive_headers = {"authorization", "x-api-key"}
        for authenticator in self.authenticators:
            self.sensitive_headers.update(getattr(authenticator, "sensitive_headers", ()))

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        getlist = getattr(headers, "getlist", None)
        if getlist is not None:  # a credential sent twice is ambiguous: refuse it
            for name in sorted(self.sensitive_headers):
                if len(getlist(name)) > 1:
                    raise AuthenticationError(f"The request carries more than one {name} header.")
        for authenticator in self.authenticators:
            principal = authenticator.authenticate(headers)
            if principal is not None:
                if principal.uri in self.admins and not principal.is_admin:
                    principal = replace(principal,
                                        global_roles=principal.global_roles | {"admin"})
                return principal
        raise AuthenticationError(
            "Sign in: send an OIDC access token or an API key as a bearer token.")
