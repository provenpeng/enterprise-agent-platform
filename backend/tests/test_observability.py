"""Request correlation survives handled and unexpected failures without logging PII."""

import json
import logging
import re
import uuid

import pytest

from app.observability.http import RequestObservabilityMiddleware


@pytest.mark.asyncio
async def test_request_id_and_templated_access_log(api_client, caplog):
    client, *_ = api_client
    missing_id = uuid.uuid4()
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        health = await client.get(
            "/api/v1/health?question=private-text",
            headers={"X-Request-ID": "untrusted-client-id"},
        )
        missing = await client.post(
            f"/api/v1/knowledge-bases/{missing_id}/ask",
            json={"query": "private-question"},
        )

    assert health.status_code == 200
    assert missing.status_code == 404
    health_id = health.headers["x-request-id"]
    missing_request_id = missing.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", health_id)
    assert re.fullmatch(r"[0-9a-f]{32}", missing_request_id)
    assert health_id != missing_request_id != "untrusted-client-id"

    entries = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "uvicorn.error" and record.getMessage().startswith("{")
    ]
    assert [entry["request_id"] for entry in entries] == [
        health_id,
        missing_request_id,
    ]
    assert [entry["route"] for entry in entries] == [
        "/api/v1/health",
        "/api/v1/knowledge-bases/{knowledge_base_id}/ask",
    ]
    assert [entry["status"] for entry in entries] == [200, 404]
    assert all(entry["duration_ms"] >= 0 for entry in entries)
    serialized = json.dumps(entries)
    assert "private-text" not in serialized
    assert "private-question" not in serialized
    assert str(missing_id) not in serialized
    assert "untrusted-client-id" not in serialized


@pytest.mark.asyncio
async def test_unexpected_error_retains_request_id_on_500(caplog):
    async def fail(scope, receive, send):
        raise RuntimeError("private exception detail")

    middleware = RequestObservabilityMiddleware(fail)
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        with pytest.raises(RuntimeError):
            await middleware(
                {"type": "http", "method": "POST", "path": "/private", "state": {}},
                receive,
                send,
            )

    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 500
    request_id = dict(messages[0]["headers"])[b"x-request-id"].decode()
    assert messages[1]["body"] == b"Internal Server Error"
    entry = json.loads(caplog.records[-1].getMessage())
    assert entry["request_id"] == request_id
    assert entry["route"] == "unmatched"
    assert entry["failure_type"] == "RuntimeError"
    assert "private" not in json.dumps(entry)
