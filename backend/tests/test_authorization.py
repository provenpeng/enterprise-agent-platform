"""JWT validation and resource ownership apply to every protected route."""

import pytest
from datetime import datetime, timedelta, timezone

from conftest import make_token


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
    ):
        response = await client.get(url, headers={"Authorization": authorization})
        assert response.status_code == 401
    assert (
        await client.get("/api/v1/health", headers={"Authorization": ""})
    ).status_code == 200


@pytest.mark.asyncio
async def test_knowledge_base_and_document_are_isolated_by_subject(api_client) -> None:
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

    own_name = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Private"}, headers=other
    )
    assert own_name.status_code == 201
