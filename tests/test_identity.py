"""Sign-in: OIDC access tokens, API keys, trusted proxy headers, and the chain."""
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from metis.identity import (
    ApiKeyAuthenticator,
    ApiKeyEntry,
    AuthenticationError,
    AuthenticatorChain,
    OIDCAuthenticator,
    TrustedHeaderAuthenticator,
)

ISSUER = "https://idp.example.com/realms/metis"
AUDIENCE = "metis-api"


@pytest.fixture(scope="module")
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "k1", "use": "sig", "alg": "RS256"})
    return key, {"keys": [jwk]}


def _token(key, **claims) -> str:
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300, "sub": "u-1", **claims}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "k1"})


def _oidc(jwks, **kw) -> OIDCAuthenticator:
    return OIDCAuthenticator(issuer=ISSUER, audience=AUDIENCE, jwks=jwks,
                             roles_claim="realm_access.roles", **kw)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_a_person_signs_in_with_their_email(signing_key):
    key, jwks = signing_key
    token = _token(key, email="Alice@Example.com", name="Alice",
                   realm_access={"roles": ["metis-admin", "offline_access"]})
    principal = _oidc(jwks).authenticate(_bearer(token))
    assert principal.uri == "human:alice@example.com"
    assert principal.display_name == "Alice" and principal.method == "oidc"
    assert principal.is_admin and principal.is_auditor


def test_a_client_signs_in_as_an_agent(signing_key):
    key, jwks = signing_key
    keycloak = _token(key, sub="9f1", azp="shift-assistant",
                      preferred_username="service-account-shift-assistant")
    assert _oidc(jwks).authenticate(_bearer(keycloak)).uri == "agent:shift-assistant"
    okta = _token(key, sub="0oa1", cid="0oa1")
    assert _oidc(jwks).authenticate(_bearer(okta)).uri == "agent:0oa1"
    auth0 = _token(key, sub="abc@clients", azp="abc", gty="client-credentials")
    assert _oidc(jwks).authenticate(_bearer(auth0)).uri == "agent:abc"


def test_the_provider_may_name_the_participant_when_configured(signing_key):
    key, jwks = signing_key
    person = _token(key, email="ops@example.com", metis_participant="service:metis-backup")
    assert _oidc(jwks).authenticate(_bearer(person)).uri == "human:ops@example.com"  # off by default
    named = _oidc(jwks, participant_claim="metis_participant")
    client = _token(key, sub="backup", azp="backup", metis_participant="service:metis-backup")
    assert named.authenticate(_bearer(client)).uri == "service:metis-backup"
    for token in (person,  # a person's token naming a service
                  _token(key, sub="bot", azp="bot", metis_participant="human:alice@corp.com")):
        with pytest.raises(AuthenticationError, match="issued to a"):
            named.authenticate(_bearer(token))


def test_an_unverified_email_does_not_name_a_person(signing_key):
    key, jwks = signing_key
    for flag in (False, "false", "FALSE"):
        token = _token(key, sub="u-9", email="ceo@example.com", email_verified=flag)
        assert _oidc(jwks).authenticate(_bearer(token)).uri == "human:u-9@idp.example.com"
    for flag in (True, "true"):
        token = _token(key, sub="u-9", email="ceo@example.com", email_verified=flag)
        assert _oidc(jwks).authenticate(_bearer(token)).uri == "human:ceo@example.com"
    silent = _token(key, sub="u-9", email="ceo@example.com")
    assert _oidc(jwks).authenticate(_bearer(silent)).uri == "human:ceo@example.com"
    strict = _oidc(jwks, require_email_verified=True)
    assert strict.authenticate(_bearer(silent)).uri == "human:u-9@idp.example.com"


def test_people_and_clients_are_told_apart(signing_key):
    key, jwks = signing_key
    # A Keycloak user whose username merely looks like a service account stays a person.
    eve = _token(key, sub="u-3", azp="metis-ui", preferred_username="service-account-eve",
                 email="eve@example.com")
    assert _oidc(jwks).authenticate(_bearer(eve)).uri == "human:eve@example.com"
    # An Entra ID app-only token without idtyp: no scp, oid equal to sub, a tenant.
    app = _token(key, sub="oid-1", oid="oid-1", tid="t-1", azp="app-123",
                 realm_access={"roles": ["metis-admin"]})
    principal = _oidc(jwks).authenticate(_bearer(app))
    assert principal.uri == "agent:app-123" and not principal.is_admin
    person = _token(key, sub="oid-2", oid="oid-2", tid="t-1", azp="app-123", scp="access",
                    email="ana@example.com")
    assert _oidc(jwks).authenticate(_bearer(person)).uri == "human:ana@example.com"


def test_global_roles_are_for_people_and_services():
    from metis.identity import Principal

    agent = Principal(uri="agent:bot", subject="s", method="api_key",
                      global_roles=frozenset({"admin", "auditor"}))
    assert not agent.is_admin and not agent.is_auditor
    service = Principal(uri="service:archive", subject="s", method="api_key",
                        global_roles=frozenset({"auditor"}))
    assert service.is_auditor and not service.is_admin
    with pytest.raises(ValueError, match="for people"):
        ApiKeyEntry(id="k", sha256="a" * 64, uri="agent:bot", global_roles=("admin",))
    with pytest.raises(ValueError, match="for people"):
        AuthenticatorChain([ApiKeyAuthenticator([])], admins=["agent:bot"])


def test_a_credential_sent_twice_is_refused():
    from starlette.datastructures import Headers

    key, digest = ApiKeyAuthenticator.generate()
    chain = AuthenticatorChain([ApiKeyAuthenticator([ApiKeyEntry(id="a", sha256=digest,
                                                                 uri="agent:a")])])
    twice = Headers(raw=[(b"authorization", f"Bearer {key}".encode()),
                         (b"authorization", b"Bearer metis_other")])
    with pytest.raises(AuthenticationError, match="more than one authorization"):
        chain.authenticate(twice)
    assert chain.authenticate(Headers(raw=[(b"authorization", f"Bearer {key}".encode())])).uri \
        == "agent:a"


def test_the_keys_file_is_written_whole_and_read_safely(tmp_path):
    path = tmp_path / "keys.yaml"
    key, digest = ApiKeyAuthenticator.generate()
    ApiKeyAuthenticator.write_file(path, [ApiKeyEntry(id="a", sha256=digest, uri="agent:a")])
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    auth = ApiKeyAuthenticator.from_file(path)
    headers = {"Authorization": f"Bearer {key}"}
    assert auth.authenticate(headers).uri == "agent:a"
    path.write_text("keys: [ {id: a, sha256: ")  # a broken file keeps the keys loaded before
    assert auth.authenticate(headers).uri == "agent:a"
    path.unlink()  # a deleted file means no keys
    with pytest.raises(AuthenticationError):
        auth.authenticate(headers)


def test_rotated_signing_keys_stop_being_accepted(signing_key, monkeypatch):
    """The provider's key set is refetched after key_cache_seconds; a removed key fails."""
    key, jwks = signing_key
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rotated = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(other.public_key()))
    rotated.update({"kid": "k2", "use": "sig", "alg": "RS256"})
    served = {"keys": jwks["keys"]}

    def fetch(client):
        data = {"keys": list(served["keys"])}
        if client.jwk_set_cache is not None:
            client.jwk_set_cache.put(data)
        return data
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch)
    auth = OIDCAuthenticator(issuer=ISSUER, audience=AUDIENCE, jwks_url="https://idp/jwks",
                             key_cache_seconds=0.01)
    token = _token(key, email="a@example.com")
    assert auth.authenticate(_bearer(token)).uri == "human:a@example.com"
    served["keys"] = [rotated]  # the provider rotated k1 out
    time.sleep(0.05)
    with pytest.raises(AuthenticationError):
        auth.authenticate(_bearer(token))


def test_an_unreachable_provider_is_unavailable_not_unauthorised(signing_key, monkeypatch):
    from metis.identity import IdentityProviderUnavailable

    key, _ = signing_key

    def down(client):
        raise jwt.PyJWKClientConnectionError("connection refused")
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", down)
    auth = OIDCAuthenticator(issuer=ISSUER, audience=AUDIENCE, jwks_url="https://idp/jwks")
    with pytest.raises(IdentityProviderUnavailable):
        auth.authenticate(_bearer(_token(key, email="a@example.com")))
    with pytest.raises(IdentityProviderUnavailable):  # not asked again for a few seconds
        auth.authenticate(_bearer(_token(key, email="a@example.com")))


def test_a_person_without_an_email_is_named_by_subject(signing_key):
    key, jwks = signing_key
    token = _token(key, sub="u-77")
    assert _oidc(jwks).authenticate(_bearer(token)).uri == "human:u-77@idp.example.com"


@pytest.mark.parametrize("claims", [
    {"exp": int(time.time()) - 3600},
    {"aud": "someone-else"},
    {"iss": "https://evil.example.com"},
])
def test_invalid_tokens_are_refused(signing_key, claims):
    key, jwks = signing_key
    with pytest.raises(AuthenticationError):
        _oidc(jwks).authenticate(_bearer(_token(key, email="a@example.com", **claims)))


def test_a_token_signed_by_another_key_is_refused(signing_key):
    _, jwks = signing_key
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthenticationError):
        _oidc(jwks).authenticate(_bearer(_token(other, email="a@example.com")))


def test_a_key_resolver_can_supply_the_signing_key(signing_key):
    key, _ = signing_key
    auth = OIDCAuthenticator(issuer=ISSUER, audience=AUDIENCE,
                             key_resolver=lambda token: key.public_key())
    assert auth.authenticate(_bearer(_token(key, email="b@example.com"))).uri == "human:b@example.com"


def test_api_keys_sign_in_and_unknown_keys_are_refused(tmp_path):
    key, digest = ApiKeyAuthenticator.generate()
    assert key.startswith("metis_") and digest not in key
    entries = [ApiKeyEntry(id="cmms", sha256=digest, uri="agent:cmms-connector",
                           display_name="CMMS connector")]
    for name in ("keys.yaml", "keys.json"):
        path = tmp_path / name
        ApiKeyAuthenticator.write_file(path, entries)
        auth = ApiKeyAuthenticator.from_file(path)
        assert auth.authenticate(_bearer(key)).uri == "agent:cmms-connector"
        assert auth.authenticate({"X-API-Key": key}).subject == "api-key:cmms"
        with pytest.raises(AuthenticationError):
            auth.authenticate(_bearer("metis_not-a-key"))
        assert auth.authenticate(_bearer("eyJ.not.ours")) is None
    with pytest.raises(ValueError):
        ApiKeyEntry(id="x", sha256="abc", uri="agent:x")
    with pytest.raises(ValueError):
        ApiKeyEntry(id="x", sha256=digest, uri="not a uri")


def test_trusted_headers_need_the_proxy_secret():
    auth = TrustedHeaderAuthenticator(secret="s3cret")
    headers = {"X-Forwarded-Email": "Ravi@Example.com", "X-Forwarded-Groups": "metis-auditor,ops",
               "X-Metis-Proxy-Secret": "s3cret"}
    principal = auth.authenticate(headers)
    assert principal.uri == "human:ravi@example.com" and principal.is_auditor
    assert not principal.is_admin
    with pytest.raises(AuthenticationError):
        auth.authenticate({**headers, "X-Metis-Proxy-Secret": "guess"})
    assert auth.authenticate({}) is None
    with pytest.raises(ValueError):
        TrustedHeaderAuthenticator(secret="")


def test_the_chain_needs_credentials_and_can_name_first_admins(signing_key):
    key, jwks = signing_key
    api_key, digest = ApiKeyAuthenticator.generate()
    chain = AuthenticatorChain(
        [_oidc(jwks), ApiKeyAuthenticator([ApiKeyEntry(id="a", sha256=digest, uri="agent:a")])],
        admins=["human:first@example.com"])
    with pytest.raises(AuthenticationError):
        chain.authenticate({})
    assert chain.authenticate(_bearer(api_key)).uri == "agent:a"
    first = chain.authenticate(_bearer(_token(key, email="first@example.com")))
    assert first.is_admin


def test_api_keys_issued_or_revoked_in_the_file_apply_without_a_restart(tmp_path):
    path = tmp_path / "keys.yaml"
    first, first_hash = ApiKeyAuthenticator.generate()
    ApiKeyAuthenticator.write_file(path, [ApiKeyEntry(id="one", sha256=first_hash, uri="agent:one")])
    auth = ApiKeyAuthenticator.from_file(path)
    assert auth.authenticate(_bearer(first)).uri == "agent:one"
    second, second_hash = ApiKeyAuthenticator.generate()
    ApiKeyAuthenticator.write_file(path, [ApiKeyEntry(id="two", sha256=second_hash, uri="agent:two")])
    assert auth.authenticate(_bearer(second)).uri == "agent:two"
    with pytest.raises(AuthenticationError):
        auth.authenticate(_bearer(first))


def test_keycloak_service_accounts_match_without_case(signing_key):
    key, jwks = signing_key
    token = _token(key, sub="9f2", azp="CMMS-Connector",
                   preferred_username="service-account-cmms-connector",
                   realm_access={"roles": ["metis-admin"]})
    principal = _oidc(jwks).authenticate(_bearer(token))
    assert principal.uri == "agent:CMMS-Connector" and not principal.is_admin


def test_an_unknown_key_while_the_provider_is_down_is_a_bad_token(signing_key, monkeypatch):
    key, jwks = signing_key
    calls = {"n": 0}

    def fetch(client):
        calls["n"] += 1
        if calls["n"] > 1:
            raise jwt.PyJWKClientConnectionError("down")
        data = {"keys": list(jwks["keys"])}
        client.jwk_set_cache.put(data)
        return data
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch)
    auth = OIDCAuthenticator(issuer=ISSUER, audience=AUDIENCE, jwks_url="https://idp/jwks")
    good = _token(key, email="a@example.com")
    assert auth.authenticate(_bearer(good)).uri == "human:a@example.com"
    forged = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": int(time.time()) + 60},
                        key, algorithm="RS256", headers={"kid": "unknown"})
    with pytest.raises(AuthenticationError, match="unknown key"):
        auth.authenticate(_bearer(forged))
    assert auth.authenticate(_bearer(good)).uri == "human:a@example.com"  # still served


def test_a_metrics_key_reads_counts_only():
    from metis.identity import Principal

    scraper = Principal(uri="service:prometheus", subject="s", method="api_key",
                        global_roles=frozenset({"metrics"}))
    assert scraper.reads_metrics and not scraper.is_auditor
    with pytest.raises(ValueError, match="metrics"):
        ApiKeyEntry(id="m", sha256="a" * 64, uri="agent:bot", global_roles=("metrics",))


def test_the_keys_file_keeps_its_mode_and_an_unreadable_file_admits_no_key(tmp_path, monkeypatch):
    path = tmp_path / "keys.yaml"
    key, digest = ApiKeyAuthenticator.generate()
    ApiKeyAuthenticator.write_file(path, [ApiKeyEntry(id="a", sha256=digest, uri="agent:a")])
    path.chmod(0o640)
    ApiKeyAuthenticator.write_file(path, [ApiKeyEntry(id="a", sha256=digest, uri="agent:a")])
    assert oct(path.stat().st_mode & 0o777) == "0o640"
    auth = ApiKeyAuthenticator.from_file(path)
    real = type(path).read_bytes

    def unreadable(self):
        if self == path:
            raise PermissionError(13, "denied")
        return real(self)
    monkeypatch.setattr(type(path), "read_bytes", unreadable)
    with pytest.raises(AuthenticationError):
        auth.authenticate({"Authorization": f"Bearer {key}"})
