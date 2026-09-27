import pytest
from fastapi.testclient import TestClient

from main import app
from store import (
    InMemoryStore,
    get_announcement_store,
    get_feedback_store,
    get_group_store,
    get_progress_store,
    get_rehearsal_store,
    get_song_store,
    get_store,
)
from test_main import OWNER_EMAIL, add_member
from tracks import InMemoryTrackStore, get_track_store

client = TestClient(app)

MP3 = b"ID3\x04" + b"\x00" * 60
PDF = b"%PDF-1.7\n" + b"\x00" * 60


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")
    monkeypatch.setenv("BOOTSTRAP_OWNER_EMAIL", OWNER_EMAIL)
    members, songs, progress, tracks = InMemoryStore(), InMemoryStore(), InMemoryStore(), InMemoryTrackStore()
    app.dependency_overrides[get_store] = lambda: members
    app.dependency_overrides[get_song_store] = lambda: songs
    app.dependency_overrides[get_progress_store] = lambda: progress
    rehearsals = InMemoryStore()
    app.dependency_overrides[get_rehearsal_store] = lambda: rehearsals
    groups = InMemoryStore()
    app.dependency_overrides[get_group_store] = lambda: groups
    feedback = InMemoryStore()
    app.dependency_overrides[get_feedback_store] = lambda: feedback
    announcements = InMemoryStore()
    app.dependency_overrides[get_announcement_store] = lambda: announcements
    app.dependency_overrides[get_track_store] = lambda: tracks
    yield {
        "members": members,
        "songs": songs,
        "progress": progress,
        "rehearsals": rehearsals,
        "groups": groups,
        "feedback": feedback,
        "announcements": announcements,
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
    assert len(client.get("/api/songs", headers=env["admin"]).json()) == 1  # same view as members
    assert len(client.get("/api/songs?scope=all", headers=env["admin"]).json()) == 2
    assert client.get("/api/songs?scope=all", headers=env["member"]).status_code == 403


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


# ---------- Per-song part ----------


def my_part(env, song_id: str, who: str = "member") -> str | None:
    return client.get(f"/api/songs/{song_id}", headers=env[who]).json()["myPart"]


def test_my_part_defaults_to_usual_part(env) -> None:
    song = make_song(env)
    assert my_part(env, song["id"]) == "lead"
    assert client.get(f"/api/songs/{song['id']}", headers=env["member"]).json()["partOverride"] is False


def test_learn_a_different_part_for_one_song(env) -> None:
    song, other = make_song(env, title="Lida Rose"), make_song(env, title="Hunchback Medley")
    res = client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    assert (res.json()["myPart"], res.json()["partOverride"]) == ("bass", True)
    assert my_part(env, song["id"]) == "bass"
    assert my_part(env, other["id"]) == "lead"
    listed = {s["title"]: (s["myPart"], s["partOverride"]) for s in client.get("/api/songs", headers=env["member"]).json()}
    assert listed == {"Lida Rose": ("bass", True), "Hunchback Medley": ("lead", False)}


def test_choice_is_per_member(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    assert my_part(env, song["id"], who="admin") == "lead"


def test_reset_to_usual_part(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    res = client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": None})
    assert (res.json()["myPart"], res.json()["partOverride"]) == ("lead", False)
    assert env["progress"].list_all() == []


def test_picking_usual_part_stores_no_override(env) -> None:
    song = make_song(env)
    res = client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "lead"})
    assert res.json()["partOverride"] is False
    assert env["progress"].list_all() == []


def test_changing_usual_part_flows_to_songs_without_a_choice(env) -> None:
    song = make_song(env)
    client.patch("/api/me", headers=env["member"], json={"part": "tenor"})
    assert my_part(env, song["id"]) == "tenor"


@pytest.mark.parametrize("body", [{"part": "soprano"}, {}, {"part": "bass", "songId": "other"}, {"part": "bass", "memberId": "x"}])
def test_my_part_rejects_bad_input(env, body: dict) -> None:
    song = make_song(env)
    assert client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json=body).status_code == 422
    assert env["progress"].list_all() == []


def test_my_part_on_retired_song_is_404(env) -> None:
    song = make_song(env, status="retired")
    res = client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    assert res.status_code == 404


def test_my_part_requires_sign_in(env) -> None:
    song = make_song(env)
    assert client.put(f"/api/songs/{song['id']}/my-part", json={"part": "bass"}).status_code == 401


def test_deleting_song_removes_part_choices(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    client.delete(f"/api/songs/{song['id']}", headers=env["admin"])
    assert env["progress"].list_all() == []


def test_removing_member_removes_part_choices(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    owner = add_member(env["members"], OWNER_EMAIL, "owner")
    assert client.delete("/api/members/google:sub-m@example.com", headers=owner).status_code == 204
    assert env["progress"].list_all() == []


def test_admin_responses_keep_my_part(env) -> None:
    song = make_song(env)
    res = client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json={"key": "F"})
    assert res.json()["myPart"] == "lead"


# ---------- Learned state ----------


def my_state(env, song_id: str, who: str = "member") -> str:
    return client.get(f"/api/songs/{song_id}", headers=env[who]).json()["myState"]


def test_state_defaults_to_not_started(env) -> None:
    song = make_song(env)
    assert my_state(env, song["id"]) == "not_started"


def test_set_state(env) -> None:
    song = make_song(env)
    res = client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json={"state": "learned"})
    assert res.json()["myState"] == "learned"
    assert my_state(env, song["id"]) == "learned"
    assert my_state(env, song["id"], who="admin") == "not_started"
    listed = client.get("/api/songs", headers=env["member"]).json()
    assert listed[0]["myState"] == "learned"


def test_state_and_part_share_one_record(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json={"state": "learning"})
    # Going back to the usual part keeps the state.
    res = client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": None})
    assert (res.json()["myPart"], res.json()["myState"]) == ("lead", "learning")
    assert len(env["progress"].list_all()) == 1


def test_not_started_without_part_leaves_no_record(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json={"state": "learning"})
    client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json={"state": "not_started"})
    assert env["progress"].list_all() == []


@pytest.mark.parametrize("body", [{"state": "mastered"}, {"state": None}, {}, {"state": "learned", "memberId": "x"}])
def test_state_rejects_bad_input(env, body: dict) -> None:
    song = make_song(env)
    assert client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json=body).status_code == 422
    assert env["progress"].list_all() == []


def test_state_on_retired_song_is_404(env) -> None:
    song = make_song(env, status="retired")
    res = client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json={"state": "learned"})
    assert res.status_code == 404


def test_state_requires_sign_in(env) -> None:
    song = make_song(env)
    assert client.put(f"/api/songs/{song['id']}/my-state", json={"state": "learned"}).status_code == 401


# ---------- Tracker ----------


def test_tracker_is_admin_only(env) -> None:
    assert client.get("/api/tracker", headers=env["member"]).status_code == 403
    assert client.get("/api/tracker").status_code == 401


def test_tracker_entries_use_per_song_part_and_state(env) -> None:
    lida, medley = make_song(env, title="Lida Rose"), make_song(env, title="Hunchback Medley")
    make_song(env, title="Old Song", status="retired")
    client.put(f"/api/songs/{medley['id']}/my-part", headers=env["member"], json={"part": "bass"})
    client.put(f"/api/songs/{medley['id']}/my-state", headers=env["member"], json={"state": "ready"})
    client.post("/api/members", headers=env["admin"], json={"email": "new@example.com", "name": "Invitee"})

    t = client.get("/api/tracker", headers=env["admin"]).json()
    assert [s["title"] for s in t["songs"]] == ["Hunchback Medley", "Lida Rose"]
    assert [m["name"] for m in t["members"]] == ["Admin", "M"]  # invited people aren't counted
    entries = {(e["songId"], e["memberId"]): (e["part"], e["state"]) for e in t["entries"]}
    member_id = "google:sub-m@example.com"
    assert entries[(medley["id"], member_id)] == ("bass", "ready")
    assert entries[(lida["id"], member_id)] == ("lead", "not_started")
    assert len(t["entries"]) == 4


# ---------- Difficulty and tags ----------


def test_create_with_difficulty_and_tags(env) -> None:
    song = make_song(env, title="Silent Night", difficulty="easy", tags=[" Christmas ", "christmas", "Slow   Ballad"])
    assert (song["difficulty"], song["tags"]) == ("easy", ["christmas", "slow ballad"])
    listed = client.get("/api/songs", headers=env["member"]).json()
    assert (listed[0]["difficulty"], listed[0]["tags"]) == ("easy", ["christmas", "slow ballad"])


def test_edit_difficulty_and_tags(env) -> None:
    song = make_song(env, difficulty="hard", tags=["contest"])
    res = client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json={"tags": ["Upbeat", "fun"], "difficulty": None})
    assert (res.json()["difficulty"], res.json()["tags"]) == (None, ["upbeat", "fun"])
    res = client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json={"tags": []})
    assert res.json()["tags"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"title": "X", "difficulty": "expert"},
        {"title": "X", "tags": ["x" * 31]},
        {"title": "X", "tags": [""]},
        {"title": "X", "tags": ["<script>"]},
        {"title": "X", "tags": [str(i) for i in range(11)]},
        {"title": "X", "tags": "christmas"},
    ],
)
def test_create_rejects_bad_tags(env, body: dict) -> None:
    assert client.post("/api/songs", headers=env["admin"], json=body).status_code == 422
    assert env["songs"].list_all() == []


@pytest.mark.parametrize("body", [{"tags": None}, {"tags": ["ok", "no/slash"]}, {"difficulty": "impossible"}])
def test_update_rejects_bad_tags(env, body: dict) -> None:
    song = make_song(env, tags=["christmas"])
    assert client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json=body).status_code == 422
    assert env["songs"].get(song["id"])["tags"] == ["christmas"]


def test_members_cannot_tag_songs(env) -> None:
    song = make_song(env)
    res = client.patch(f"/api/songs/{song['id']}", headers=env["member"], json={"tags": ["mine"]})
    assert res.status_code == 403
    assert env["songs"].get(song["id"])["tags"] == []


# ---------- Type: full song or barbershop tag ----------


def test_type_defaults_to_full_song(env) -> None:
    assert make_song(env)["kind"] == "song"
    # Songs stored before the field existed read as full songs.
    env["songs"].upsert({k: v for k, v in env["songs"].list_all()[0].items() if k != "kind"})
    assert client.get("/api/songs", headers=env["member"]).json()[0]["kind"] == "song"


def test_set_and_change_type(env) -> None:
    song = make_song(env, title="Tag: Goodbye My Coney Island Baby", kind="tag")
    assert song["kind"] == "tag"
    res = client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json={"kind": "song"})
    assert res.json()["kind"] == "song"


@pytest.mark.parametrize("body", [{"kind": "medley"}, {"kind": None}, {"kind": "Tag"}])
def test_type_rejects_bad_input(env, body: dict) -> None:
    song = make_song(env)
    assert client.patch(f"/api/songs/{song['id']}", headers=env["admin"], json=body).status_code == 422
    assert env["songs"].get(song["id"])["kind"] == "song"


def test_members_cannot_change_type(env) -> None:
    song = make_song(env)
    assert client.patch(f"/api/songs/{song['id']}", headers=env["member"], json={"kind": "tag"}).status_code == 403


# ---------- Files changed after the upload checks (security audit L-3) ----------


def test_link_refused_if_file_is_overwritten_after_checks(env) -> None:
    """The upload link stays valid for a few minutes after `complete`; a swap in that window
    must not be served to members."""
    song = make_song(env)
    assert upload(env, song["id"], "score", PDF).status_code == 200
    assert client.get(f"/api/songs/{song['id']}/files/score", headers=env["member"]).status_code == 200
    env["tracks"].blobs[f"{song['id']}/score.pdf"] = b"<html><script>alert(1)</script>"
    res = client.get(f"/api/songs/{song['id']}/files/score", headers=env["member"])
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "file_changed"


def test_reupload_through_complete_is_served_again(env) -> None:
    song = make_song(env)
    assert upload(env, song["id"], "lead", MP3).status_code == 200
    assert upload(env, song["id"], "lead", MP3 + b"new take").status_code == 200
    assert client.get(f"/api/songs/{song['id']}/files/lead", headers=env["member"]).status_code == 200


def test_files_from_before_the_check_still_work(env) -> None:
    song = make_song(env)
    upload(env, song["id"], "lead", MP3)
    doc = env["songs"].get(song["id"])
    env["songs"].upsert({**doc, "files": {"lead": {"size": len(MP3), "uploadedAt": doc["files"]["lead"]["uploadedAt"]}}})
    assert client.get(f"/api/songs/{song['id']}/files/lead", headers=env["member"]).status_code == 200


def test_upload_links_are_shorter_than_read_links() -> None:
    import tracks

    assert tracks.UPLOAD_SAS_LIFETIME.total_seconds() == 300
    assert tracks.SAS_LIFETIME.total_seconds() == 900
