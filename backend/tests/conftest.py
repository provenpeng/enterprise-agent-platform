import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import httpx
import jwt
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.tenant import Tenant


@lru_cache
def _test_keys() -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


def make_token(subject: str, **overrides: object) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "tenant_id": str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"enterprise-agent-platform:{subject}")
        ),
        "role": "admin",
        "iss": "enterprise-agent-platform",
        "aud": "enterprise-agent-api",
        "iat": now,
        "exp": now + timedelta(hours=1),
        **overrides,
    }
    return jwt.encode(claims, _test_keys()[0], algorithm="RS256")


@pytest_asyncio.fixture
async def api_client(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[httpx.AsyncClient, AsyncEngine, async_sessionmaker[AsyncSession], Settings]
]:
    database_url = make_url(get_settings().database_url)
    test_database_name = f"eap_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(
        database_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{test_database_name}"'))

    test_database_url = database_url.set(database=test_database_name)
    test_engine = create_async_engine(test_database_url)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    settings = Settings(
        database_url=test_database_url.render_as_string(hide_password=False),
        upload_dir=tmp_path / "uploads",
        auth_public_key_path=tmp_path / "auth-public.pem",
    )
    settings.auth_public_key_path.write_bytes(_test_keys()[1])

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    try:
        async with test_engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                Tenant(
                    id=uuid.uuid5(
                        uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user"
                    ),
                    name="Test tenant",
                )
            )
            await session.commit()
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_settings] = lambda: settings
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {make_token('test-user')}"},
        ) as client:
            yield client, test_engine, session_factory, settings
    finally:
        app.dependency_overrides.clear()
        await test_engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{test_database_name}"'))
        await admin_engine.dispose()
