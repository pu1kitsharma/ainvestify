"""Google/default OIDC adapter using Authlib PKCE and signed ID-token validation."""
from __future__ import annotations
import os
from dataclasses import dataclass
from urllib.parse import urlsplit
import requests


def app_origin():
    origin = os.environ.get("APP_ORIGIN", "https://localhost:5173").rstrip("/")
    url = urlsplit(origin)
    if url.username or url.password or url.query or url.fragment or url.path:
        raise ValueError("APP_ORIGIN must be an origin")
    if url.scheme != "https":
        if not (os.environ.get("ALLOW_LOOPBACK_HTTP") == "1"
                and os.environ.get("APP_ENV", "development") == "development"
                and url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("HTTPS required; HTTP is restricted to explicit loopback development")
    if not url.hostname:
        raise ValueError("APP_ORIGIN requires a hostname")
    return origin


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def load(cls):
        issuer = os.environ.get("OIDC_ISSUER", "https://accounts.google.com").rstrip("/")
        if urlsplit(issuer).scheme != "https" or urlsplit(issuer).query or urlsplit(issuer).fragment:
            raise ValueError("An allowlisted HTTPS issuer is required")
        client, secret = os.environ.get("OIDC_CLIENT_ID", ""), os.environ.get("OIDC_CLIENT_SECRET", "")
        if not client or not secret:
            raise ValueError("Google/OIDC client registration is not configured")
        return cls(issuer, client, secret, app_origin() + "/api/auth/callback")


def _json_get(url):
    response = requests.get(url, timeout=15, allow_redirects=False)
    response.raise_for_status()
    if len(response.content) > 1024 * 1024:
        raise ValueError("Identity provider response too large")
    return response.json()


class OIDCProvider:
    def __init__(self, config):
        self.config = config

    def metadata(self):
        data = _json_get(self.config.issuer + "/.well-known/openid-configuration")
        if data.get("issuer") != self.config.issuer:
            raise ValueError("Identity provider issuer mismatch")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            url = urlsplit(data[field])
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("Invalid identity provider endpoint")
        return data

    def client(self):
        from authlib.integrations.requests_client import OAuth2Session
        return OAuth2Session(self.config.client_id, self.config.client_secret,
            scope="openid email profile", redirect_uri=self.config.redirect_uri, code_challenge_method="S256")

    def authorization_url(self, state, nonce, verifier):
        with self.client() as client:
            return client.create_authorization_url(self.metadata()["authorization_endpoint"],
                state=state, nonce=nonce, code_verifier=verifier)[0]

    def verify_code(self, code, nonce, verifier):
        from authlib.jose import JsonWebToken
        from authlib.oidc.core import CodeIDToken
        metadata = self.metadata()
        with self.client() as client:
            token = client.fetch_token(metadata["token_endpoint"], code=code,
                code_verifier=verifier, timeout=15, allow_redirects=False)
        claims = JsonWebToken(["RS256", "ES256"]).decode(token["id_token"],
            _json_get(metadata["jwks_uri"]), claims_cls=CodeIDToken,
            claims_options={"iss": {"essential": True, "value": self.config.issuer},
                "sub": {"essential": True}, "aud": {"essential": True, "value": self.config.client_id},
                "exp": {"essential": True}, "iat": {"essential": True}, "nonce": {"essential": True}},
            claims_params={"nonce": nonce, "client_id": self.config.client_id,
                "access_token": token.get("access_token")})
        claims.validate(leeway=30)
        if not isinstance(claims['sub'],str) or not claims['sub'].strip():
            raise ValueError('Invalid subject identity')
        return claims["iss"], claims["sub"]
