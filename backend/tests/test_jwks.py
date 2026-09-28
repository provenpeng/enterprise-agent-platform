"""Externally issued tokens use bounded, rotating RS256 JWKS verification."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api import auth
from app.api.jwks import JwksResolver, JwksUnavailable
from app.core.config import Settings


def _key_pair(kid: str) -> tuple[bytes, dict]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return pem, jwk


def _token(private: bytes, kid: str, **overrides: object) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "test-user",
        "tenant_id": str(
            uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
        ),
        "role": "admin",
        "iss": "enterprise-agent-platform",
        "aud": "enterprise-agent-api",
        "iat": now,
        "exp": now + timedelta(hours=1),
        **overrides,
    }
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


@pytest.mark.asyncio
async def test_jwks_authentication_refreshes_on_rotated_kid(
    api_client, monkeypatch
) -> None:
    client, _, _, settings = api_client
    settings.auth_jwks_url = "https://idp.example/jwks"
    first_private, first_jwk = _key_pair("first")
    second_private, second_jwk = _key_pair("second")
    keys = [first_jwk]
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == "https://idp.example/jwks"
        return httpx.Response(200, json={"keys": keys})

    resolver = JwksResolver(
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ),
        miss_refresh_seconds=0,
    )
    monkeypatch.setattr(auth, "jwks_resolver", resolver)
    first = {"Authorization": f"Bearer {_token(first_private, 'first')}"}
    assert (await client.get("/api/v1/me", headers=first)).status_code == 200
    assert (await client.get("/api/v1/me", headers=first)).status_code == 200
    assert calls == 1
    keys.append(second_jwk)
    second = {"Authorization": f"Bearer {_token(second_private, 'second')}"}
    assert (await client.get("/api/v1/me", headers=second)).status_code == 200
    assert calls == 2
    bad_kid = {"Authorization": f"Bearer {_token(second_private, 'missing')}"}
    assert (await client.get("/api/v1/me", headers=bad_kid)).status_code == 401
    wrong_issuer = {
        "Authorization": f"Bearer {_token(second_private, 'second', iss='wrong')}"
    }
    assert (await client.get("/api/v1/me", headers=wrong_issuer)).status_code == 401


@pytest.mark.asyncio
async def test_jwks_failure_is_503_and_bad_headers_do_not_fetch(
    api_client, monkeypatch
) -> None:
    client, _, _, settings = api_client
    settings.auth_jwks_url = "https://idp.example/jwks"
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    monkeypatch.setattr(
        auth,
        "jwks_resolver",
        JwksResolver(
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            )
        ),
    )
    unsigned = jwt.encode({"sub": "x"}, "test-secret-" * 4, algorithm="HS256")
    assert (
        await client.get("/api/v1/me", headers={"Authorization": f"Bearer {unsigned}"})
    ).status_code == 401
    assert calls == 0
    private, _ = _key_pair("first")
    assert (
        await client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {_token(private, 'first')}"},
        )
    ).status_code == 503
    assert calls == 1


@pytest.mark.asyncio
async def test_jwks_rejects_oversized_or_wrong_algorithm() -> None:
    private, jwk = _key_pair("valid")
    del private
    responses = [
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, json={"keys": [{**jwk, "alg": "RS512"}]}),
    ]
    resolver = JwksResolver(
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: responses.pop(0))
        )
    )
    with pytest.raises(JwksUnavailable):
        await resolver.key("https://idp.example/jwks", "valid")
    with pytest.raises(JwksUnavailable):
        await resolver.key("https://idp.example/jwks", "valid")


def test_jwks_url_requires_https() -> None:
    with pytest.raises(ValueError, match="AUTH_JWKS_URL must use HTTPS"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://user:pass@localhost/db",
            auth_jwks_url="http://idp.example/jwks",
        )
