"""Request correlation and structured access logs without user content."""

import json
import logging
import uuid
from time import perf_counter
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("uvicorn.error")
REQUEST_ID_HEADER = b"x-request-id"


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp, api_prefix: str = "") -> None:
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status_code = 500
        response_started = False
        failure_type: str | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_started = True
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != REQUEST_ID_HEADER
                ]
                headers.append((REQUEST_ID_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            failure_type = type(exc).__name__
            if not response_started:
                await send_with_id(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send_with_id(
                    {"type": "http.response.body", "body": b"Internal Server Error"}
                )
            raise
        finally:
            route: Any = scope.get("route")
            route_path = getattr(route, "path", None)
            if (
                route_path is not None
                and self.api_prefix
                and scope["path"].startswith(self.api_prefix + "/")
                and not route_path.startswith(self.api_prefix + "/")
            ):
                route_path = self.api_prefix + route_path
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": str(scope.get("method", ""))[:16],
                        "route": route_path if route_path is not None else "unmatched",
                        "status": status_code,
                        "duration_ms": round((perf_counter() - started) * 1000),
                        "failure_type": failure_type,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
