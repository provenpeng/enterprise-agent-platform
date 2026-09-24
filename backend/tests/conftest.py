import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest_asyncio.fixture
async def api_client(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, AsyncEngine, async_sessionmaker[AsyncSession], Settings]]:
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
    )

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    try:
        async with test_engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_settings] = lambda: settings
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, test_engine, session_factory, settings
    finally:
        app.dependency_overrides.clear()
        await test_engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{test_database_name}"'))
        await admin_engine.dispose()
