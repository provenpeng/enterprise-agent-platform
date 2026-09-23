import hashlib
import uuid
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from starlette.datastructures import Headers

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.document import Document, DocumentStatus
from app.services.document import upload_document


@pytest_asyncio.fixture
async def api_client(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, AsyncEngine, async_sessionmaker, Settings]]:
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

    async def override_db() -> AsyncIterator:
        async with session_factory() as session:
            yield session

    try:
        async with test_engine.begin() as connection:
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


@pytest.mark.asyncio
async def test_create_list_and_get_knowledge_base(api_client) -> None:
    client, _, _, _ = api_client
    created = await client.post(
        "/api/v1/knowledge-bases", json={"name": "  Policies  ", "description": "Rules"}
    )

    assert created.status_code == 201
    assert created.json()["name"] == "Policies"
    assert created.json()["status"] == "ACTIVE"
    knowledge_base_id = created.json()["id"]

    listed = await client.get("/api/v1/knowledge-bases")
    fetched = await client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [knowledge_base_id]
    assert fetched.status_code == 200
    assert fetched.json() == created.json()


@pytest.mark.asyncio
async def test_upload_txt_and_reject_same_checksum(api_client) -> None:
    client, _, session_factory, settings = api_client
    knowledge_base_id = (
        await client.post("/api/v1/knowledge-bases", json={"name": "Operations"})
    ).json()["id"]
    content = b"Refund policy: contact support.\n"
    upload_url = f"/api/v1/knowledge-bases/{knowledge_base_id}/documents"

    uploaded = await client.post(
        upload_url, files={"file": ("rules.txt", content, "text/plain")}
    )
    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["status"] == "UPLOADED"
    assert body["active_index_version"] is None
    assert body["checksum"] == hashlib.sha256(content).hexdigest()
    assert body["file_type"] == "text/plain"
    stored_file = Path(settings.upload_dir) / knowledge_base_id / body["id"] / "original.txt"
    assert stored_file.read_bytes() == content
    assert body["storage_uri"] == stored_file.resolve().as_uri()

    listed = await client.get(upload_url)
    fetched = await client.get(f"/api/v1/documents/{body['id']}")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]
    assert fetched.status_code == 200
    assert fetched.json() == body

    duplicate = await client.post(
        upload_url, files={"file": ("same-content.txt", content, "text/plain")}
    )
    assert duplicate.status_code == 409
    assert len(list(settings.upload_dir.rglob("original.txt"))) == 1

    async with session_factory() as session:
        session.add(
            Document(
                knowledge_base_id=uuid.UUID(knowledge_base_id),
                filename="another-name.txt",
                file_type="text/plain",
                storage_uri="file:///unused",
                checksum=body["checksum"],
                status=DocumentStatus.UPLOADED,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_upload_pdf_and_markdown(api_client) -> None:
    client, _, _, settings = api_client
    knowledge_base_id = (
        await client.post("/api/v1/knowledge-bases", json={"name": "Formats"})
    ).json()["id"]
    upload_url = f"/api/v1/knowledge-bases/{knowledge_base_id}/documents"

    for filename, content, mime, expected_type in (
        ("guide.pdf", b"%PDF-1.4\nexample", "application/pdf", "application/pdf"),
        ("notes.md", b"# Notes\n", "text/plain", "text/markdown"),
    ):
        response = await client.post(
            upload_url, files={"file": (filename, content, mime)}
        )
        assert response.status_code == 201
        assert response.json()["file_type"] == expected_type
        stored_file = (
            settings.upload_dir
            / knowledge_base_id
            / response.json()["id"]
            / f"original{Path(filename).suffix}"
        )
        assert stored_file.read_bytes() == content


@pytest.mark.asyncio
async def test_upload_validation_and_missing_knowledge_base(api_client) -> None:
    client, _, _, settings = api_client
    knowledge_base_id = (
        await client.post("/api/v1/knowledge-bases", json={"name": "Validation"})
    ).json()["id"]
    upload_url = f"/api/v1/knowledge-bases/{knowledge_base_id}/documents"

    assert (
        await client.post(upload_url, files={"file": ("bad.exe", b"bad", "application/octet-stream")})
    ).status_code == 415
    assert (
        await client.post(upload_url, files={"file": ("bad.pdf", b"not a pdf", "application/pdf")})
    ).status_code == 415
    assert (
        await client.post(upload_url, files={"file": ("bad.txt", b"text", "application/pdf")})
    ).status_code == 415

    settings.max_upload_size_bytes = 3
    assert (
        await client.post(upload_url, files={"file": ("big.txt", b"four", "text/plain")})
    ).status_code == 413
    assert (
        await client.post(
            f"/api/v1/knowledge-bases/{uuid.uuid4()}/documents",
            files={"file": ("valid.txt", b"ok", "text/plain")},
        )
    ).status_code == 404
    assert not settings.upload_dir.exists()


@pytest.mark.asyncio
async def test_database_failure_removes_saved_file(api_client) -> None:
    client, engine, session_factory, settings = api_client
    knowledge_base_id = uuid.UUID(
        (await client.post("/api/v1/knowledge-bases", json={"name": "Failure"})).json()["id"]
    )
    async with engine.begin() as connection:
        await connection.execute(
            text("ALTER TABLE documents ADD CONSTRAINT ck_test_reject_upload "
                 "CHECK (filename <> 'db-fail.txt')")
        )

    upload = UploadFile(
        file=BytesIO(b"saved before database failure"),
        filename="db-fail.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await upload_document(session, knowledge_base_id, upload, settings)

    assert not list(settings.upload_dir.rglob("*"))
    async with session_factory() as session:
        assert (await session.scalars(select(Document))).all() == []
