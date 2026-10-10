"""TP-080A: real JWT cryptography and every registered route are fail-closed."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.security import JwtVerifier


ALLOWED = str(uuid4())
OTHER = str(uuid4())
ORIGIN = "https://taskplanner.example.com"
ISSUER = "https://example.supabase.co/auth/v1"


class OfflineJwks:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        if jwt.get_unverified_header(token).get("kid") != "test-key":
            raise jwt.InvalidTokenError()
        return SimpleNamespace(key=self.public_key)


@pytest.fixture
def secure_client():
    settings = Settings(
        env="production",
        auth_mode="supabase",
        supabase_url="https://example.supabase.co",
        supabase_allowed_sub=ALLOWED,
        cors_origins=ORIGIN,
    )
    settings.validate_security()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = JwtVerifier(settings, OfflineJwks(private_key.public_key()))
    original_settings = app.state.security_settings
    original_verifier = app.state.jwt_verifier
    app.state.security_settings = settings
    app.state.jwt_verifier = verifier
    try:
        with TestClient(app) as client:
            yield client, private_key, verifier
    finally:
        app.state.security_settings = original_settings
        app.state.jwt_verifier = original_verifier


def make_token(key, **changes):
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": ALLOWED,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "role": "authenticated",
    }
    payload.update(changes)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test-key"})


def test_health_is_public_but_all_other_registered_routes_are_private(secure_client):
    client, _, _ = secure_client
    assert client.get("/api/health").status_code == 200
    paths = {route.path for route in app.routes if route.path != "/api/health"}
    assert any(path.startswith("/api/behavior") for path in paths)
    assert any(path.startswith("/api/work-sessions") for path in paths)
    assert any(path.startswith("/api/capacity") for path in paths)
    assert any(path.startswith("/api/review") for path in paths)
    assert any(path.startswith("/api/tasks") for path in paths)
    for path in sorted(paths):
        response = client.get(path)
        assert response.status_code == 401, (path, response.status_code, response.text)
    assert client.post("/api/tasks", json={"title": "Not authorized"}).status_code == 401
    # Newly added/unrecognized routes must also fail closed, not silently bypass security.
    assert client.get("/api/forgotten-future-endpoint").status_code == 401


def test_valid_jwt_reaches_private_endpoint_and_jwks_is_project_scoped(secure_client):
    client, key, verifier = secure_client
    assert verifier.jwks_url == ISSUER + "/.well-known/jwks.json"
    token = make_token(key)
    response = client.get("/openapi.json", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("case", [
    "malformed", "bad-signature", "wrong-issuer", "wrong-audience",
    "expired", "no-exp", "no-iat", "unsigned-algorithm", "other-user",
])
def test_invalid_jwts_are_refused(secure_client, case):
    client, key, _ = secure_client
    if case == "malformed":
        token = "not-a-jwt"
    elif case == "bad-signature":
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = make_token(other_key)
    elif case == "wrong-issuer":
        token = make_token(key, iss="https://attacker.supabase.co/auth/v1")
    elif case == "wrong-audience":
        token = make_token(key, aud="anon")
    elif case == "expired":
        token = make_token(key, exp=int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()))
    elif case == "no-exp":
        payload = jwt.decode(make_token(key), options={"verify_signature": False})
        payload.pop("exp")
        token = jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test-key"})
    elif case == "no-iat":
        payload = jwt.decode(make_token(key), options={"verify_signature": False})
        payload.pop("iat")
        token = jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test-key"})
    elif case == "unsigned-algorithm":
        token = jwt.encode({"sub": ALLOWED}, "attacker", algorithm="HS256")
    else:
        token = make_token(key, sub=OTHER)
    response = client.get("/api/behavior", headers={"Authorization": "Bearer " + token})
    assert response.status_code == (403 if case == "other-user" else 401)


def test_cors_does_not_allow_unknown_origin(secure_client):
    client, _, _ = secure_client
    # The app initializes CORS once from offline test settings; production
    # validates its own HTTPS origin at startup.
    test_origin = "http://localhost:5173"
    allowed = client.options("/api/tasks", headers={
        "Origin": test_origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == test_origin
    denied = client.options("/api/tasks", headers={
        "Origin": "https://attacker.example", "Access-Control-Request-Method": "POST",
    })
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_production_fails_closed_without_authorization_configuration():
    with pytest.raises(ValueError):
        Settings(env="production", auth_mode="local", cors_origins=ORIGIN).validate_security()
    with pytest.raises(ValueError):
        Settings(env="production", auth_mode="supabase", cors_origins=ORIGIN,
                 supabase_url=None, supabase_allowed_sub=None).validate_security()
    with pytest.raises(ValueError):
        Settings(env="production", auth_mode="supabase", cors_origins="*",
                 supabase_url="https://example.supabase.co",
                 supabase_allowed_sub=ALLOWED).validate_security()
    with pytest.raises(ValueError):
        Settings(env="production", auth_mode="supabase", cors_origins="http://localhost:5173",
                 supabase_url="https://example.supabase.co",
                 supabase_allowed_sub=ALLOWED).validate_security()
