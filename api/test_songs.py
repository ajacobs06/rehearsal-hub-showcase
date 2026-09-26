import pytest
from fastapi.testclient import TestClient

from main import app
from store import InMemoryStore, get_song_store, get_store
from test_main import OWNER_EMAIL, add_member
from tracks import InMemoryTrackStore, get_track_store

client = TestClient(app)

MP3 = b"ID3\x04" + b"\x00" * 60
PDF = b"%PDF-1.7\n" + b"\x00" * 60


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")
    monkeypatch.setenv("BOOTSTRAP_OWNER_EMAIL", OWNER_EMAIL)
    members, songs, tracks = InMemoryStore(), InMemoryStore(), InMemoryTrackStore()
    app.dependency_overrides[get_store] = lambda: members
    app.dependency_overrides[get_song_store] = lambda: songs
    app.dependency_overrides[get_track_store] = lambda: tracks
    yield {
        "members": members,
        "songs": songs,
        "tracks": tracks,
        "admin": add_member(members, "admin@example.com", "admin"),
        "member": add_member(members, "m@example.com", "member"),
    }
    app.dependency_overrides.clear()


def make_song(env, **body) -> dict:
    res = client.post("/api/songs", headers=env["admin"], json={"title": "Lida Rose", **body})
    assert res.status_code == 201
    return res.json()


def upload(env, song_id: str, kind: str, data: bytes):
    path = f"{song_id}/{'score.pdf' if kind == 'score' else f'{kind}.mp3'}"
    assert client.post(f"/api/songs/{song_id}/files/{kind}/upload", headers=env["admin"]).status_code == 200
    env["tracks"].blobs[path] = data  # stands in for the browser's direct PUT to Blob Storage
    return client.post(f"/api/songs/{song_id}/files/{kind}/complete", headers=env["admin"])


# ---------- Visibility ----------


def test_songs_require_sign_in(env) -> None:
    assert client.get("/api/songs").status_code == 401


def test_member_sees_active_songs_but_not_retired(env) -> None:
    make_song(env, title="Lida Rose")
    retired = make_song(env, title="Old Favourite", status="retired")
    titles = [s["title"] for s in client.get("/api/songs", headers=env["member"]).json()]
    assert titles == ["Lida Rose"]
    assert client.get(f"/api/songs/{retired['id']}", headers=env["member"]).status_code == 404
    assert len(client.get("/api/songs", headers=env["admin"]).json()) == 2


def test_member_gets_read_link_for_uploaded_file_only(env) -> None:
    song = make_song(env)
    upload(env, song["id"], "lead", MP3)
    res = client.get(f"/api/songs/{song['id']}/files/lead", headers=env["member"])
    assert res.status_code == 200
    assert "sig=read" in res.json()["url"]
    assert client.get(f"/api/songs/{song['id']}/files/bass", headers=env["member"]).status_code == 404


def test_retired_song_files_hidden_from_members(env) -> None:
    song = make_song(env)
    upload(env, song["id"], "lead", MP3)
    client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json={"status": "retired"})
    assert client.get(f"/api/songs/{song['id']}/files/lead", headers=env["member"]).status_code == 404


# ---------- Admin-only actions ----------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/songs", {"title": "X"}),
        ("patch", "/api/songs/{id}", {"title": "X"}),
        ("delete", "/api/songs/{id}", None),
        ("post", "/api/songs/{id}/files/lead/upload", None),
        ("post", "/api/songs/{id}/files/lead/complete", None),
        ("delete", "/api/songs/{id}/files/lead", None),
    ],
)
def test_member_cannot_manage_songs(env, method: str, path: str, body: dict | None) -> None:
    song = make_song(env)
    res = client.request(method, path.format(id=song["id"]), headers=env["member"], json=body)
    assert res.status_code == 403
    assert env["songs"].get(song["id"])["title"] == "Lida Rose"


# ---------- Validation ----------


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 121},
        {"title": "X", "status": "archived"},
        {"title": "X", "id": "forged"},
        {"title": "X", "files": {"lead": {"size": 1, "uploadedAt": "now"}}},
    ],
)
def test_create_song_rejects_bad_input(env, body: dict) -> None:
    assert client.post("/api/songs", headers=env["admin"], json=body).status_code == 422
    assert env["songs"].list_all() == []


@pytest.mark.parametrize("body", [{"title": None}, {"status": None}, {"files": {}}, {"createdAt": "x"}])
def test_update_song_rejects_bad_input(env, body: dict) -> None:
    song = make_song(env)
    assert client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json=body).status_code == 422


def test_unknown_file_kind_rejected(env) -> None:
    song = make_song(env)
    res = client.post(f"/api/songs/{song['id']}/files/soprano/upload", headers=env["admin"])
    assert res.status_code == 422


# ---------- Upload checks ----------


def test_valid_uploads_are_recorded(env) -> None:
    song = make_song(env)
    assert upload(env, song["id"], "lead", MP3).status_code == 200
    res = upload(env, song["id"], "score", PDF)
    assert set(res.json()["files"]) == {"lead", "score"}


@pytest.mark.parametrize(
    ("kind", "data", "reason"),
    [
        ("lead", b"", "empty"),
        ("lead", b"<html><script>alert(1)</script>", "wrong_type"),
        ("lead", PDF, "wrong_type"),
        ("score", MP3, "wrong_type"),
        ("lead", b"ID3" + b"\x00" * (50 * 1024 * 1024), "too_large"),
    ],
)
def test_bad_uploads_are_deleted(env, kind: str, data: bytes, reason: str) -> None:
    song = make_song(env)
    res = upload(env, song["id"], kind, data)
    assert res.status_code == 400
    assert res.json()["detail"]["reason"] == reason
    assert env["tracks"].blobs == {}
    assert env["songs"].get(song["id"])["files"] == {}


def test_complete_without_upload_fails(env) -> None:
    song = make_song(env)
    res = client.post(f"/api/songs/{song['id']}/files/lead/complete", headers=env["admin"])
    assert res.json()["detail"]["reason"] == "upload_missing"


def test_delete_song_removes_its_files(env) -> None:
    song = make_song(env)
    upload(env, song["id"], "lead", MP3)
    upload(env, song["id"], "score", PDF)
    assert client.delete(f"/api/songs/{song['id']}", headers=env["admin"]).status_code == 204
    assert env["tracks"].blobs == {}
    assert env["songs"].get(song["id"]) is None


def test_delete_file(env) -> None:
    song = make_song(env)
    upload(env, song["id"], "lead", MP3)
    res = client.delete(f"/api/songs/{song['id']}/files/lead", headers=env["admin"])
    assert res.json()["files"] == {}
    assert env["tracks"].blobs == {}
