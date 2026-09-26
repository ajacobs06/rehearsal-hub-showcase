"""Request guards that run before FastAPI parses anything, and security headers on every response.

- FastAPI reads and validates a request body before it runs auth dependencies, so without the body
  cap an anonymous caller could make the server hold arbitrarily large bodies in memory.
- CSRF: every /api write must come from our own origin and, if it has a body, be JSON. Easy Auth's
  session cookie is SameSite=None, so the browser would otherwise send it with cross-site requests.
"""
import json
import os
import threading
import time
from functools import lru_cache
from urllib.parse import urlsplit
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


def _origin(url: str) -> str | None:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else None


@lru_cache
def security_headers() -> list[tuple[bytes, bytes]]:
    # Audio, score links and uploads go straight between the browser and Blob Storage.
    storage = _origin(os.environ.get("STORAGE_ACCOUNT_URL", "")) or ""
    csp = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            f"media-src 'self' blob: {storage}".strip(),
            f"connect-src 'self' {storage}".strip(),
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "upgrade-insecure-requests",
        ]
    )
    return [
        (b"content-security-policy", csp.encode()),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
        (b"cross-origin-opener-policy", b"same-origin"),
    ]


def allowed_origin(request: Request) -> str:
    """APP_URL in production; locally, whatever host the request came in on (e.g. the Vite proxy)."""
    return _origin(os.environ.get("APP_URL", "")) or f"{request.url.scheme}://{request.headers.get('host', '')}".lower()


def same_origin(request: Request) -> bool:
    """Browsers send Origin on every POST/PUT/PATCH/DELETE; Referer is the fallback. A request with
    neither isn't from a browser page, so it can't carry a victim's cookie cross-site."""
    expected = allowed_origin(request)
    origin = request.headers.get("origin")
    if origin is not None:
        return origin.lower() == expected  # includes the opaque "null" origin: refused
    referer = request.headers.get("referer")
    if referer is not None:
        return _origin(referer) == expected
    return True


def is_json(request: Request) -> bool:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    return media_type == "application/json"


class SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"server"]
                message["headers"] = headers + security_headers()
            await send(message)

        await self._handle(scope, receive, send_with_headers)

    async def _handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope)
        path: str = scope["path"]
        is_api = path == "/api" or path.startswith("/api/")
        is_write = scope["method"] in WRITE_METHODS

        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY):
            await _reply(send, 413, {"reason": "too_large"})
            return

        if is_api and is_write and not same_origin(request):
            await _reply(send, 403, {"reason": "cross_origin"})
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
        if is_api and is_write and body and not is_json(request):
            # Forms can only send urlencoded, multipart or text/plain; our front end always sends JSON.
            await _reply(send, 415, {"reason": "json_required"})
            return
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
