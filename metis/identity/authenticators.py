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
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from ..integrations.chap.participants import URI_RE
from .principal import AuthenticationError, Principal

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
    revoked with ``metis server api-key`` take effect without a restart.
    """

    def __init__(self, entries: Iterable[ApiKeyEntry], *, path: str | Path | None = None) -> None:
        self._set(list(entries))
        self.path = Path(path) if path else None
        self._digest = self._file_digest()

    def _set(self, entries: list[ApiKeyEntry]) -> None:
        ids = [e.id for e in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("API key ids must be unique")
        self.entries = entries

    def _file_digest(self) -> str | None:
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path else None
        except OSError:  # missing, or being replaced: keep the keys already loaded
            return None

    def _reload_if_changed(self) -> None:
        """Reread the keys file when its contents change (it is small; the check is cheap)."""
        if self.path is None:
            return
        digest = self._file_digest()
        if digest is not None and digest != self._digest:
            self._set(self.read_file(self.path))
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
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"keys": [e.as_dict() for e in entries]}
        if path.suffix.lower() == ".json":
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        else:
            import yaml

            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

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
def _is_client_token(claims: Mapping[str, Any]) -> bool:
    """True for a token a client obtained for itself (client credentials), as identity
    providers mark it: Entra ID's ``idtyp``, Keycloak's service-account user, Auth0's grant
    type and ``@clients`` subject, or a subject equal to the client id (Okta and others)."""
    if claims.get("idtyp") == "app" or claims.get("gty") == "client-credentials":
        return True
    if str(claims.get("preferred_username", "")).startswith("service-account-"):
        return True
    sub = str(claims.get("sub", ""))
    if sub.endswith("@clients"):
        return True
    clients = {claims.get(k) for k in ("azp", "client_id", "cid", "appid")} - {None}
    return bool(sub) and sub in {str(c) for c in clients}


class OIDCAuthenticator:
    """Verify JWT access tokens issued by an OpenID Connect provider.

    The token must be signed by one of the provider's keys, carry the configured issuer and
    audience, and be unexpired. People sign in as ``human:<email>``; a client signing in with
    its own credentials becomes ``agent:<client id>``. An identity provider may set the
    participant URI explicitly in the ``participant_claim`` claim. Roles in ``roles_claim``
    (a dotted path such as ``realm_access.roles``) grant the global admin and auditor roles.
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
        participant_claim: str = "metis_participant",
        admin_role: str = "metis-admin",
        auditor_role: str = "metis-auditor",
        key_resolver: Callable[[str], Any] | None = None,
        http_timeout: float = 5.0,
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
        self._key_resolver = key_resolver

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
            client = jwt.PyJWKClient(self.jwks_url or self._discover_jwks_url(),
                                     cache_keys=True, lifespan=300, timeout=int(self.http_timeout))
            self._key_resolver = lambda token: client.get_signing_key_from_jwt(token).key
        return self._key_resolver

    # -- authentication --
    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        token = _bearer(headers)
        if token is None or token.startswith(API_KEY_PREFIX) or token.count(".") != 2:
            return None
        import jwt

        try:
            key = self._resolver()(token)
            claims = jwt.decode(token, key=key, algorithms=self.algorithms,
                                audience=self.audience, issuer=self.issuer, leeway=self.leeway,
                                options={"require": ["exp", "iss", "sub"]})
        except AuthenticationError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid access token: {exc}") from None
        except Exception as exc:  # key lookup or provider discovery failed
            raise AuthenticationError(f"Could not verify the access token: {exc}") from None
        return self.principal_from_claims(claims)

    def participant_uri(self, claims: Mapping[str, Any]) -> str:
        explicit = claims.get(self.participant_claim)
        if (isinstance(explicit, str) and URI_RE.match(explicit)
                and explicit.split(":", 1)[0] in _PARTICIPANT_TYPES):
            return explicit
        if _is_client_token(claims):
            client = next((claims[k] for k in ("azp", "client_id", "cid", "appid") if claims.get(k)),
                          claims["sub"])
            return f"agent:{str(client).removesuffix('@clients')}"
        email = claims.get(self.email_claim)
        if isinstance(email, str) and "@" in email and claims.get("email_verified", True) is not False:
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

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        for authenticator in self.authenticators:
            principal = authenticator.authenticate(headers)
            if principal is not None:
                if principal.uri in self.admins and not principal.is_admin:
                    principal = replace(principal,
                                        global_roles=principal.global_roles | {"admin"})
                return principal
        raise AuthenticationError(
            "Sign in: send an OIDC access token or an API key as a bearer token.")
