import pytest
from fastapi.testclient import TestClient

from main import app
from test_main import OWNER_EMAIL, add_member
from test_rehearsals import make_rehearsal, rsvp
from test_songs import env, make_song  # noqa: F401  (env is a fixture)

client = TestClient(app)
MEMBER_ID = "google:sub-m@example.com"


def send(env, message="The Bass player won't load on my phone", page="/songs/abc", who="member"):
    return client.post("/api/feedback", headers=env[who], json={"message": message, "page": page})


# ---------- Feedback ----------


def test_member_sends_feedback(env) -> None:
    res = send(env)
    assert res.status_code == 201
    body = res.json()
    assert (body["memberId"], body["name"], body["page"], body["status"]) == (MEMBER_ID, "M", "/songs/abc", "new")


@pytest.mark.parametrize(
    "body",
    [{"message": ""}, {"message": "   "}, {"message": "x" * 2001}, {"message": "hi", "page": "x" * 201},
     {"message": "hi", "memberId": "someone-else"}, {"message": "hi", "status": "done"}, {}],
)
def test_feedback_rejects_bad_input(env, body: dict) -> None:
    assert client.post("/api/feedback", headers=env["member"], json=body).status_code == 422
    assert env["feedback"].list_all() == []


def test_feedback_requires_sign_in(env) -> None:
    assert client.post("/api/feedback", json={"message": "hi"}).status_code == 401


def test_feedback_daily_limit(env) -> None:
    for _ in range(20):
        assert send(env).status_code == 201
    assert send(env).status_code == 429


def test_members_cannot_read_or_manage_feedback(env) -> None:
    item = send(env).json()
    assert client.get("/api/feedback", headers=env["member"]).status_code == 403
    assert client.patch(f"/api/feedback/{item['id']}", headers=env["member"], json={"status": "done"}).status_code == 403
    assert client.delete(f"/api/feedback/{item['id']}", headers=env["member"]).status_code == 403


def test_admin_inbox(env) -> None:
    first = send(env, message="first").json()
    send(env, message="second")
    client.patch(f"/api/feedback/{first['id']}", headers=env["admin"], json={"status": "done"})
    listed = [(f["message"], f["status"]) for f in client.get("/api/feedback", headers=env["admin"]).json()]
    assert listed == [("second", "new"), ("first", "done")]
    assert client.patch(f"/api/feedback/{first['id']}", headers=env["admin"], json={"status": "archived"}).status_code == 422
    assert client.delete(f"/api/feedback/{first['id']}", headers=env["admin"]).status_code == 204
    assert len(env["feedback"].list_all()) == 1


# ---------- Your data ----------


def test_export_contains_only_my_data(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json={"state": "learned"})
    client.put(f"/api/songs/{song['id']}/my-state", headers=env["admin"], json={"state": "ready"})
    r = make_rehearsal(env)
    rsvp(env, r["id"], "yes")
    rsvp(env, r["id"], "no", who="admin")
    send(env)
    send(env, who="admin")
    data = client.get("/api/me/export", headers=env["member"]).json()
    assert data["member"]["id"] == MEMBER_ID
    assert [(p["songId"], p["state"]) for p in data["progress"]] == [(song["id"], "learned")]
    assert [(x["rehearsalId"], x["response"]) for x in data["rsvps"]] == [(r["id"], "yes")]
    assert [f["memberId"] for f in data["feedback"]] == [MEMBER_ID]


def test_export_requires_sign_in(env) -> None:
    assert client.get("/api/me/export").status_code == 401


def test_delete_my_account_removes_everything(env) -> None:
    song = make_song(env)
    client.put(f"/api/songs/{song['id']}/my-part", headers=env["member"], json={"part": "bass"})
    r = make_rehearsal(env)
    rsvp(env, r["id"], "yes")
    send(env)
    assert client.delete("/api/me", headers=env["member"]).status_code == 204
    assert env["members"].get(MEMBER_ID) is None
    assert env["progress"].find("memberId", MEMBER_ID) == []
    assert env["rehearsals"].get(r["id"])["rsvps"] == {}
    assert env["feedback"].find("memberId", MEMBER_ID) == []
    # Signing in again finds no invite.
    assert client.get("/api/me", headers=env["member"]).json()["detail"]["reason"] == "not_invited"


def test_owner_must_hand_over_before_deleting(env) -> None:
    owner = add_member(env["members"], OWNER_EMAIL, "owner")
    res = client.delete("/api/me", headers=owner)
    assert (res.status_code, res.json()["detail"]["reason"]) == (400, "owner_must_hand_over")
    assert env["members"].get(f"google:sub-{OWNER_EMAIL}") is not None


def test_removing_member_removes_their_feedback(env) -> None:
    send(env)
    owner = add_member(env["members"], OWNER_EMAIL, "owner")
    assert client.delete(f"/api/members/{MEMBER_ID}", headers=owner).status_code == 204
    assert env["feedback"].list_all() == []
