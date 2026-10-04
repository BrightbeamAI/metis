"""Authenticated identity for a multi-user Metis deployment.

A request's identity comes from its credentials, never from its body: an OIDC access token, an
API key, or headers set by a trusted reverse proxy. Each authenticator turns credentials into a
``Principal`` whose CHAP participant URI is the identity Metis records.
"""
from .authenticators import (
    ApiKeyAuthenticator,
    ApiKeyEntry,
    Authenticator,
    AuthenticatorChain,
    OIDCAuthenticator,
    TrustedHeaderAuthenticator,
)
from .principal import GLOBAL_ROLES, AuthenticationError, Principal

__all__ = [
    "GLOBAL_ROLES",
    "ApiKeyAuthenticator",
    "ApiKeyEntry",
    "AuthenticationError",
    "Authenticator",
    "AuthenticatorChain",
    "OIDCAuthenticator",
    "Principal",
    "TrustedHeaderAuthenticator",
]
