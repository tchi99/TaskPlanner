"""Supabase access-token verification at the FastAPI trust boundary (TP-080A)."""

from hmac import compare_digest
from urllib.error import URLError

import jwt
from jwt import PyJWKClient, PyJWTError

from app.config import Settings


class AuthenticationFailure(Exception):
    """Missing, malformed, expired or untrusted bearer token."""


class AuthorizationFailure(Exception):
    """Valid token belonging to another Supabase user."""


class JwtVerifier:
    """Only project JWKS signing keys are trusted. Never consult token-provided URLs."""

    ALGORITHMS = ("RS256", "ES256")

    def __init__(self, settings: Settings, jwks_client: PyJWKClient | None = None):
        self.settings = settings
        project_url = (settings.supabase_url or "").rstrip("/")
        self.issuer = f"{project_url}/auth/v1"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self.jwks_client = jwks_client or PyJWKClient(
            self.jwks_url, cache_jwk_set=True, lifespan=300, timeout=3
        )

    def verify(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.ALGORITHMS:
                raise AuthenticationFailure()
            signing_key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self.ALGORITHMS),
                audience=self.settings.supabase_audience,
                issuer=self.issuer,
                options={"require": ["sub", "exp", "iss", "aud", "iat"]},
                leeway=0,
            )
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject:
                raise AuthenticationFailure()
        except (PyJWTError, URLError, ValueError, TypeError) as exc:
            raise AuthenticationFailure() from exc
        if not compare_digest(subject, self.settings.supabase_allowed_sub or ""):
            raise AuthorizationFailure()
        return subject
