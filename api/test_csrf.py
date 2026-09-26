"""CSRF and security headers (security audit M-2, L-1). The test client's own origin is http://testserver."""
import pytest

import security
from store import InMemoryStore
from test_main import add_member, client, store  # noqa: F401  (store is a fixture)
from test_songs import env, make_song  # noqa: F401  (env is a fixture)

SELF = "http://testserver"
EVIL = "https://evil.example"


@pytest.fixture(autouse=True)
def fresh_headers() -> None:
    security.security_headers.cache_clear()


# Every kind of write a cross-site page could aim at, including the two bodyless POSTs.
WRITES = [
    ("POST", "/api/feedback", {"message": "hi"}),
    ("POST", "/api/members", {"email": "x@example.com", "name": "X"}),
    ("POST", "/api/songs", {"title": "Injected"}),
    ("POST", "/api/rehearsals", {"start": "2030-05-01T19:00:00+00:00", "venue": "Fake"}),
    ("POST", "/api/groups", {"name": "Evil"}),
    ("POST", "/api/songs/SONG/files/lead/upload", None),
    ("POST", "/api/songs/SONG/files/lead/complete", None),
    ("PATCH", "/api/me", {"part": "bass"}),
    ("PUT", "/api/songs/SONG/my-state", {"state": "learned"}),
    ("DELETE", "/api/songs/SONG", None),
    ("DELETE", "/api/me", None),
]


def send(env, method: str, path: str, body, song: str, **headers):
    return client.request(method, path.replace("SONG", song), headers={**env["admin"], **headers}, json=body)


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_cross_origin_writes_are_refused(env, method, path, body) -> None:
    song = make_song(env)["id"]
    res = send(env, method, path, body, song, Origin=EVIL)
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "cross_origin"


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_foreign_referer_without_origin_is_refused(env, method, path, body) -> None:
    song = make_song(env)["id"]
    assert send(env, method, path, body, song, Referer=f"{EVIL}/page").status_code == 403


def test_opaque_null_origin_is_refused(env) -> None:
    """Sandboxed iframes and some redirects send `Origin: null`."""
    assert send(env, "POST", "/api/feedback", {"message": "hi"}, "", Origin="null").status_code == 403


def test_same_origin_writes_work(env) -> None:
    song = make_song(env)["id"]
    assert send(env, "POST", "/api/feedback", {"message": "hi"}, song, Origin=SELF).status_code == 201
    assert send(env, "PATCH", "/api/me", {"part": "bass"}, song, Origin=SELF).status_code == 200
    assert send(env, "POST", "/api/songs/SONG/files/lead/upload", None, song, Origin=SELF).status_code == 200
    assert send(env, "PUT", "/api/songs/SONG/my-state", {"state": "learned"}, song, Referer=f"{SELF}/songs/x").status_code == 200


def test_app_url_is_the_only_allowed_origin_when_set(env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_URL", "https://hub.example")
    assert send(env, "POST", "/api/feedback", {"message": "hi"}, "", Origin=SELF).status_code == 403
    assert send(env, "POST", "/api/feedback", {"message": "hi"}, "", Origin="https://hub.example").status_code == 201
    # Same host, wrong scheme.
    assert send(env, "POST", "/api/feedback", {"message": "hi"}, "", Origin="http://hub.example").status_code == 403


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", None]
)
def test_writes_with_a_body_must_be_json(env, content_type) -> None:
    """The three content types an HTML form can send (and none at all) are refused even same-origin."""
    headers = {**env["member"], "Origin": SELF}
    if content_type:
        headers["Content-Type"] = content_type
    res = client.post("/api/feedback", headers=headers, content=b'{"message":"hi"}')
    assert res.status_code == 415
    assert res.json()["detail"]["reason"] == "json_required"


def test_json_with_charset_is_fine(env) -> None:
    headers = {**env["member"], "Origin": SELF, "Content-Type": "application/json; charset=utf-8"}
    assert client.post("/api/feedback", headers=headers, content=b'{"message":"hi"}').status_code == 201


def test_cross_origin_reads_are_not_blocked_but_get_no_cors(env) -> None:
    """Reads are safe without CORS: the attacker's page can't see the response."""
    res = client.get("/api/me", headers={**env["member"], "Origin": EVIL})
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers
    pre = client.options("/api/me", headers={"Origin": EVIL, "Access-Control-Request-Method": "PATCH"})
    assert "access-control-allow-origin" not in pre.headers


def test_security_headers_on_every_response(store: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_ACCOUNT_URL", "https://acct.blob.core.windows.net/")
    for res in (client.get("/api/health"), client.get("/api/songs"), client.post("/api/feedback", json={})):
        h = res.headers
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp and "unsafe" not in csp
        assert "frame-ancestors 'none'" in csp
        assert "media-src 'self' blob: https://acct.blob.core.windows.net" in csp
        assert "connect-src 'self' https://acct.blob.core.windows.net;" in csp
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in h["permissions-policy"]
        assert "server" not in h
