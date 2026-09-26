"""JWT validation and resource ownership apply to every protected route."""

import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from conftest import make_token
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services.document import upload_document
from app.services.errors import NotFound
from app.services.index_jobs import enqueue_reindex


@pytest.mark.asyncio
async def test_missing_invalid_and_expired_tokens_are_rejected(api_client) -> None:
    client, _, _, _ = api_client
    url = "/api/v1/knowledge-bases"
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    for authorization in (
        "",
        "Bearer invalid",
        f"Bearer {make_token('user', aud='wrong')}",
        f"Bearer {make_token('user', exp=expired)}",
        f"Bearer {make_token('legacy-unassigned')}",
        f"Bearer {make_token('user', tenant_id='not-a-uuid')}",
        f"Bearer {make_token('user', role='unknown')}",
        f"Bearer {make_token('user', role=['admin'])}",
        f"Bearer {make_token('user', tenant_id=None)}",
    ):
        response = await client.get(url, headers={"Authorization": authorization})
        assert response.status_code == 401
    assert (
        await client.get("/api/v1/health", headers={"Authorization": ""})
    ).status_code == 200


@pytest.mark.asyncio
async def test_knowledge_base_and_document_are_isolated_by_tenant(api_client) -> None:
    client, _, _, _ = api_client
    created = await client.post("/api/v1/knowledge-bases", json={"name": "Private"})
    assert created.status_code == 201
    knowledge_base_id = created.json()["id"]
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        files={"file": ("private.txt", b"private content", "text/plain")},
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]

    other = {"Authorization": f"Bearer {make_token('other-user')}"}
    assert (await client.get("/api/v1/knowledge-bases", headers=other)).json() == []
    assert (
        await client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}", headers=other)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
            headers=other,
            files={"file": ("other.txt", b"other", "text/plain")},
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/documents/{document_id}", headers=other)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/documents/{document_id}/chunks", headers=other)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/documents/{document_id}/index-jobs", headers=other)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/documents/{document_id}/index-jobs", headers=other)
    ).status_code == 404

    same_subject_other_tenant = {
        "Authorization": f"Bearer {make_token('test-user', tenant_id=str(uuid.uuid4()))}"
    }
    assert (
        await client.get(
            f"/api/v1/documents/{document_id}", headers=same_subject_other_tenant
        )
    ).status_code == 404

    provisioned = await client.post(
        "/api/v1/tenants", json={"name": "Other tenant"}, headers=other
    )
    assert provisioned.status_code == 201
    own_name = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Private"}, headers=other
    )
    assert own_name.status_code == 201


@pytest.mark.asyncio
async def test_write_services_enforce_tenant_scope_without_route_guards(
    api_client,
) -> None:
    client, _, sessions, settings = api_client
    created = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Service scope"}
    )
    knowledge_base_id = uuid.UUID(created.json()["id"])
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        files={"file": ("owned.txt", b"owned", "text/plain")},
    )
    document_id = uuid.UUID(uploaded.json()["id"])
    outsider_tenant = uuid.uuid4()
    upload = UploadFile(
        file=BytesIO(b"unauthorized"),
        filename="denied.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    stored_paths = set(settings.upload_dir.rglob("*"))
    async with sessions() as db:
        with pytest.raises(NotFound):
            await upload_document(
                db,
                knowledge_base_id,
                upload,
                settings,
                tenant_id=outsider_tenant,
            )
        with pytest.raises(NotFound):
            await enqueue_reindex(db, document_id, settings, tenant_id=outsider_tenant)
    assert upload.file.tell() == 0
    assert set(settings.upload_dir.rglob("*")) == stored_paths
    jobs = await client.get(f"/api/v1/documents/{document_id}/index-jobs")
    assert len(jobs.json()) == 1


@pytest.mark.asyncio
async def test_tenant_members_share_reads_and_viewer_cannot_write(api_client) -> None:
    client, _, _, _ = api_client
    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    created = await client.post("/api/v1/knowledge-bases", json={"name": "Shared"})
    assert created.status_code == 201
    knowledge_base_id = created.json()["id"]
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        files={"file": ("shared.txt", b"shared content", "text/plain")},
    )
    document_id = uploaded.json()["id"]
    viewer = {
        "Authorization": f"Bearer {make_token('colleague', tenant_id=str(tenant_id), role='viewer')}"
    }
    identity = await client.get("/api/v1/me", headers=viewer)
    assert identity.status_code == 200
    assert identity.json() == {
        "subject": "colleague",
        "tenant_id": str(tenant_id),
        "role": "viewer",
    }
    assert (
        await client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}", headers=viewer)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/documents/{document_id}", headers=viewer)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/documents/{document_id}/chunks", headers=viewer)
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/knowledge-bases", headers=viewer, json={"name": "Denied"}
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
            headers=viewer,
            files={"file": ("denied.txt", b"denied", "text/plain")},
        )
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/documents/{document_id}/index-jobs", headers=viewer)
    ).status_code == 403
    assert (
        await client.post("/api/v1/tenants", headers=viewer, json={"name": "Denied"})
    ).status_code == 403

    colleague_admin = {
        "Authorization": f"Bearer {make_token('colleague', tenant_id=str(tenant_id))}"
    }
    assert (
        await client.post(
            "/api/v1/knowledge-bases", headers=colleague_admin, json={"name": "Second"}
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/v1/knowledge-bases", headers=colleague_admin, json={"name": "Shared"}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_tenant_must_be_provisioned_before_writes(api_client) -> None:
    client, _, _, _ = api_client
    new_tenant = {"Authorization": f"Bearer {make_token('new-admin')}"}
    assert (
        await client.post(
            "/api/v1/knowledge-bases", headers=new_tenant, json={"name": "No tenant"}
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/tenants", headers=new_tenant, json={"name": "New tenant"}
        )
    ).status_code == 201
    assert (
        await client.post("/api/v1/tenants", headers=new_tenant, json={"name": "Again"})
    ).status_code == 409
    assert (await client.get("/api/v1/tenants/current", headers=new_tenant)).json()[
        "name"
    ] == "New tenant"
