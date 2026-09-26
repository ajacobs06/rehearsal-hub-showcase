"""Request guards that run before FastAPI parses anything (see security-audit H-1, L-2).

FastAPI reads and validates a request body before it runs auth dependencies, so without this an
anonymous caller could make the server hold arbitrarily large bodies in memory.
"""
import json
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.requests import Request

from auth import get_principal

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

MAX_BODY = 1024 * 1024  # the largest real body (a song or rehearsal) is a few KB
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class RateLimiter:
    """Token bucket per key, in memory. Each gunicorn worker keeps its own buckets, so the
    effective limit is per worker; that's enough to stop a runaway script."""

    def __init__(self, capacity: int, per_seconds: float) -> None:
        self.capacity = capacity
        self.rate = capacity / per_seconds
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) > 10_000:  # bounded memory; members number in the tens
                self._buckets.clear()
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# Per signed-in account, across all /api routes. A busy page makes a handful of requests.
api_limiter = RateLimiter(capacity=120, per_seconds=60)
# Each invite sends an email from the society's sender.
invite_limiter = RateLimiter(capacity=30, per_seconds=3600)


async def _reply(send: Send, status: int, detail: dict[str, str]) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        path: str = scope["path"]
        is_api = path == "/api" or path.startswith("/api/")
        is_write = scope["method"] in WRITE_METHODS

        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY):
            await _reply(send, 413, {"reason": "too_large"})
            return

        if is_api and path != "/api/health":
            principal = get_principal(request)
            if principal is None and is_write:
                # Refuse before reading the body; reads still reach the route for its usual 401.
                await _reply(send, 401, {"reason": "not_signed_in"})
                return
            if principal is not None and not api_limiter.allow(principal.member_id):
                await _reply(send, 429, {"reason": "too_many_requests"})
                return

        # Read the body here, up to the cap, so a missing or false Content-Length can't get past it.
        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY:
                await _reply(send, 413, {"reason": "too_large"})
                return
            chunks.append(chunk)
            more = message.get("more_body", False)

        body = b"".join(chunks)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
