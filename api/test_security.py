import pytest

import security
from store import InMemoryStore
from test_main import FakeMailer, add_member, client, mailer, principal, store  # noqa: F401  (fixtures)


def test_oversized_body_is_refused_by_length(store: InMemoryStore) -> None:
    headers = add_member(store, "m@example.com", "member")
    big = b'{"message":"' + b"a" * (security.MAX_BODY + 1) + b'"}'
    res = client.post("/api/feedback", headers={**headers, "Content-Type": "application/json"}, content=big)
    assert res.status_code == 413
    assert res.json()["detail"]["reason"] == "too_large"


def test_oversized_body_is_refused_without_content_length(store: InMemoryStore) -> None:
    """A chunked body has no Content-Length; the streamed bytes are counted instead."""
    headers = add_member(store, "m@example.com", "member")

    def chunks():
        for _ in range(3):
            yield b"a" * (security.MAX_BODY // 2)

    res = client.post("/api/feedback", headers={**headers, "Content-Type": "application/json"}, content=chunks())
    assert res.status_code == 413


def test_bad_content_length_is_refused(store: InMemoryStore) -> None:
    headers = add_member(store, "m@example.com", "member")
    res = client.post("/api/feedback", headers={**headers, "Content-Length": "-1"}, content=b"")
    assert res.status_code == 413


def test_anonymous_write_is_refused_before_the_body_is_read(store: InMemoryStore) -> None:
    """401, not 422: validation (which would read the body) never runs for anonymous writes."""
    for method in ("post", "put", "patch", "delete"):
        res = client.request(method, "/api/feedback", headers={"Content-Type": "application/json"}, content=b"{}")
        assert res.status_code == 401, method
        assert res.json()["detail"]["reason"] == "not_signed_in"


def test_anonymous_read_still_gets_401(store: InMemoryStore) -> None:
    assert client.get("/api/songs").status_code == 401


def test_normal_requests_still_work(store: InMemoryStore) -> None:
    headers = add_member(store, "m@example.com", "member")
    res = client.post("/api/feedback", headers=headers, json={"message": "Works"})
    assert res.status_code == 201
    assert client.patch("/api/me", headers=headers, json={"part": "bass"}).json()["part"] == "bass"


def test_health_is_not_rate_limited(store: InMemoryStore) -> None:
    for _ in range(security.api_limiter.capacity + 5):
        assert client.get("/api/health").status_code == 200


def test_rate_limit_per_member(store: InMemoryStore) -> None:
    a = add_member(store, "a@example.com", "member")
    b = add_member(store, "b@example.com", "member")
    for _ in range(security.api_limiter.capacity):
        assert client.get("/api/me", headers=a).status_code == 200
    res = client.get("/api/me", headers=a)
    assert res.status_code == 429
    assert res.json()["detail"]["reason"] == "too_many_requests"
    # Someone else is unaffected.
    assert client.get("/api/me", headers=b).status_code == 200


def test_rate_limit_refills(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = security.RateLimiter(capacity=2, per_seconds=60)
    clock = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: clock[0])
    assert limiter.allow("k") and limiter.allow("k")
    assert not limiter.allow("k")
    clock[0] += 30  # half the window refills one token
    assert limiter.allow("k")
    assert not limiter.allow("k")


def test_invites_are_limited_per_admin(store: InMemoryStore, mailer: FakeMailer) -> None:
    admin = add_member(store, "admin@example.com", "admin")
    for i in range(security.invite_limiter.capacity):
        res = client.post("/api/members", headers=admin, json={"email": f"new{i}@example.com", "name": "New"})
        assert res.status_code == 201
    res = client.post("/api/members", headers=admin, json={"email": "onemore@example.com", "name": "New"})
    assert res.status_code == 429
    assert res.json()["detail"]["reason"] == "too_many_invites"
    assert len(mailer.sent) == security.invite_limiter.capacity


def test_forged_principal_does_not_count_as_signed_in_without_easy_auth(
    store: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WEBSITE_AUTH_ENABLED")
    res = client.post("/api/feedback", headers=principal("m@example.com"), json={"message": "hi"})
    assert res.status_code == 401
