import hashlib
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers

from app.models.document import Document, DocumentStatus
from app.models.index_job import IndexJob
from app.services import document as document_service
from app.services.document import upload_document


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
    second = await client.post("/api/v1/knowledge-bases", json={"name": "Finance"})
    assert second.status_code == 201

    listed = await client.get("/api/v1/knowledge-bases")
    fetched = await client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}")
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} == {
        knowledge_base_id,
        second.json()["id"],
    }
    assert fetched.status_code == 200
    assert fetched.json() == created.json()

    first_page = await client.get("/api/v1/knowledge-bases?limit=1&offset=0")
    second_page = await client.get("/api/v1/knowledge-bases?limit=1&offset=1")
    assert {first_page.json()[0]["id"], second_page.json()[0]["id"]} == {
        knowledge_base_id,
        second.json()["id"],
    }
    assert (await client.get("/api/v1/knowledge-bases?limit=0")).status_code == 422


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
    assert "storage_uri" not in body
    stored_file = (
        Path(settings.upload_dir) / knowledge_base_id / body["id"] / "original.txt"
    )
    assert stored_file.read_bytes() == content
    async with session_factory() as session:
        stored_document = await session.get(Document, uuid.UUID(body["id"]))
        assert stored_document is not None
        assert (
            stored_document.storage_uri
            == f"{knowledge_base_id}/{body['id']}/original.txt"
        )

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

    uploaded_ids = []
    for filename, content, mime, expected_type in (
        ("guide.pdf", b"%PDF-1.4\nexample", "application/pdf", "application/pdf"),
        ("notes.md", b"# Notes\n", "text/plain", "text/markdown"),
    ):
        response = await client.post(
            upload_url, files={"file": (filename, content, mime)}
        )
        assert response.status_code == 201
        assert response.json()["file_type"] == expected_type
        uploaded_ids.append(response.json()["id"])
        stored_file = (
            settings.upload_dir
            / knowledge_base_id
            / response.json()["id"]
            / f"original{Path(filename).suffix}"
        )
        assert stored_file.read_bytes() == content

    first_page = await client.get(f"{upload_url}?limit=1&offset=0")
    second_page = await client.get(f"{upload_url}?limit=1&offset=1")
    assert {first_page.json()[0]["id"], second_page.json()[0]["id"]} == set(
        uploaded_ids
    )
    assert (await client.get(f"{upload_url}?limit=101")).status_code == 422


@pytest.mark.asyncio
async def test_upload_does_not_hold_transaction_during_file_io(
    api_client, monkeypatch
) -> None:
    client, engine, session_factory, settings = api_client
    knowledge_base_id = uuid.UUID(
        (
            await client.post("/api/v1/knowledge-bases", json={"name": "Transactions"})
        ).json()["id"]
    )
    async with session_factory() as session:

        class CheckedUpload(UploadFile):
            async def read(self, size: int = -1) -> bytes:
                assert not session.in_transaction()
                assert engine.pool.checkedout() == 0
                return await super().read(size)

        upload = CheckedUpload(
            file=BytesIO(b"transaction boundary"),
            filename="boundary.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        real_to_thread = document_service.asyncio.to_thread

        async def checked_to_thread(func, *args, **kwargs):
            if func is document_service._save_original:
                assert not session.in_transaction()
                assert engine.pool.checkedout() == 0
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(document_service.asyncio, "to_thread", checked_to_thread)
        document = await upload_document(
            session,
            knowledge_base_id,
            upload,
            settings,
            tenant_id=uuid.uuid5(
                uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user"
            ),
        )
        assert document.status == DocumentStatus.UPLOADED


@pytest.mark.asyncio
async def test_upload_validation_and_missing_knowledge_base(api_client) -> None:
    client, _, _, settings = api_client
    knowledge_base_id = (
        await client.post("/api/v1/knowledge-bases", json={"name": "Validation"})
    ).json()["id"]
    upload_url = f"/api/v1/knowledge-bases/{knowledge_base_id}/documents"

    assert (
        await client.post(
            upload_url, files={"file": ("bad.exe", b"bad", "application/octet-stream")}
        )
    ).status_code == 415
    assert (
        await client.post(
            upload_url, files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}
        )
    ).status_code == 415
    assert (
        await client.post(
            upload_url, files={"file": ("bad.txt", b"text", "application/pdf")}
        )
    ).status_code == 415

    settings.max_upload_size_bytes = 3
    assert (
        await client.post(
            upload_url, files={"file": ("big.txt", b"four", "text/plain")}
        )
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
        (await client.post("/api/v1/knowledge-bases", json={"name": "Failure"})).json()[
            "id"
        ]
    )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE documents ADD CONSTRAINT ck_test_reject_upload "
                "CHECK (filename <> 'db-fail.txt')"
            )
        )

    upload = UploadFile(
        file=BytesIO(b"saved before database failure"),
        filename="db-fail.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await upload_document(
                session,
                knowledge_base_id,
                upload,
                settings,
                tenant_id=uuid.uuid5(
                    uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user"
                ),
            )

    assert not list(settings.upload_dir.rglob("*"))
    async with session_factory() as session:
        assert (await session.scalars(select(Document))).all() == []
        assert (await session.scalars(select(IndexJob))).all() == []
