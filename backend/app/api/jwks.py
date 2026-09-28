"""Bounded asynchronous JWKS resolution for externally issued RS256 tokens."""

import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Callable

import httpx
import jwt


class JwksUnavailable(Exception):
    """The configured identity provider could not supply usable keys."""


@dataclass
class _Entry:
    fetched_at: float
    keys: dict[str, object]


class JwksResolver:
    def __init__(
        self,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        ttl_seconds: float = 300,
        miss_refresh_seconds: float = 5,
    ) -> None:
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=3, follow_redirects=False)
        )
        self._ttl_seconds = ttl_seconds
        self._miss_refresh_seconds = miss_refresh_seconds
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def key(self, url: str, kid: str) -> object | None:
        async with self._lock:
            entry = self._entries.get(url)
            age = monotonic() - entry.fetched_at if entry else float("inf")
            if entry and age < self._ttl_seconds and kid in entry.keys:
                return entry.keys[kid]
            if entry and age < self._miss_refresh_seconds and kid not in entry.keys:
                return None
            try:
                async with self._client_factory() as client:
                    response = await client.get(url)
                    response.raise_for_status()
            except httpx.HTTPError as exc:
                raise JwksUnavailable from exc
            if len(response.content) > 65536:
                raise JwksUnavailable("JWKS response is too large")
            try:
                document = json.loads(response.content)
                raw_keys = document["keys"]
                if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 32:
                    raise ValueError("JWKS key count is invalid")
                keys = {}
                for raw in raw_keys:
                    if not isinstance(raw, dict):
                        raise ValueError("JWKS entry is invalid")
                    name = raw.get("kid")
                    if (
                        not isinstance(name, str)
                        or not 1 <= len(name) <= 128
                        or name in keys
                    ):
                        raise ValueError("JWKS key ID is invalid or duplicated")
                    if (
                        raw.get("kty") != "RSA"
                        or raw.get("alg", "RS256") != "RS256"
                        or raw.get("use", "sig") != "sig"
                    ):
                        continue
                    keys[name] = jwt.PyJWK.from_dict(raw, algorithm="RS256").key
                if not keys:
                    raise ValueError("JWKS has no RS256 signing keys")
            except (KeyError, TypeError, ValueError, jwt.PyJWKError) as exc:
                raise JwksUnavailable("JWKS document is invalid") from exc
            self._entries[url] = _Entry(fetched_at=monotonic(), keys=keys)
            return keys.get(kid)


jwks_resolver = JwksResolver()
