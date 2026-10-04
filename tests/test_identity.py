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


def test_the_provider_may_name_the_participant(signing_key):
    key, jwks = signing_key
    token = _token(key, email="ops@example.com", metis_participant="service:metis-backup")
    assert _oidc(jwks).authenticate(_bearer(token)).uri == "service:metis-backup"


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
