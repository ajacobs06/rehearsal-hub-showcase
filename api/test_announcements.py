import pytest
from fastapi.testclient import TestClient

from main import app
from test_main import OWNER_EMAIL, add_member
from test_songs import env  # noqa: F401  (env is a fixture)

client = TestClient(app)
MEMBER_ID = "google:sub-m@example.com"


def post(env, who="admin", **body):
    return client.post("/api/announcements", headers=env[who], json={"title": "Concert dress", "body": "Black.", **body})


def make_group(env, name="Quartet") -> str:
    return client.post("/api/groups", headers=env["admin"], json={"name": name}).json()["id"]


def join(env, group_id: str, member_id: str = MEMBER_ID) -> None:
    assert client.put(f"/api/groups/{group_id}/members", headers=env["admin"], json={"memberIds": [member_id]}).status_code == 200


def titles(env, who="member", **params) -> list[str]:
    res = client.get("/api/announcements", headers=env[who], params=params)
    assert res.status_code == 200
    return [a["title"] for a in res.json()]


def test_admin_posts_and_member_reads(env) -> None:
    res = post(env, title="Concert dress", body="Black, with the violet tie.\n\nBring it Tuesday.")
    assert res.status_code == 201
    a = res.json()
    assert (a["title"], a["authorName"], a["groups"], a["updatedAt"]) == ("Concert dress", "Admin", [], None)
    assert "authorId" not in a
    assert titles(env) == ["Concert dress"]
    assert client.get(f"/api/announcements/{a['id']}", headers=env["member"]).json()["body"].endswith("Tuesday.")


def test_members_cannot_post_edit_or_delete(env) -> None:
    a = post(env).json()
    assert post(env, who="member").status_code == 403
    assert client.patch(f"/api/announcements/{a['id']}", headers=env["member"], json={"title": "x"}).status_code == 403
    assert client.delete(f"/api/announcements/{a['id']}", headers=env["member"]).status_code == 403
    assert client.get("/api/announcements?scope=all", headers=env["member"]).status_code == 403


def test_sign_in_required(env) -> None:
    assert client.get("/api/announcements").status_code == 401


def test_newest_first_and_limit(env, monkeypatch: pytest.MonkeyPatch) -> None:
    import announcements

    for i, t in enumerate(["First", "Second", "Third"]):
        monkeypatch.setattr(announcements, "now", lambda i=i: f"2026-10-0{i + 1}T12:00:00+00:00")
        post(env, title=t)
    assert titles(env) == ["Third", "Second", "First"]
    assert titles(env, limit=1) == ["Third"]
    assert client.get("/api/announcements?limit=0", headers=env["member"]).status_code == 422
    assert client.get("/api/announcements?limit=101", headers=env["member"]).status_code == 422


def test_group_announcements_only_reach_that_group(env) -> None:
    quartet = make_group(env)
    private = post(env, title="Quartet call", groups=[quartet]).json()
    post(env, title="Everyone")
    assert titles(env) == ["Everyone"]
    assert client.get(f"/api/announcements/{private['id']}", headers=env["member"]).status_code == 404
    # Admins manage every post, but their own list is what they'd see as a member.
    assert "Quartet call" in titles(env, who="admin", scope="all")
    join(env, quartet)
    assert sorted(titles(env)) == ["Everyone", "Quartet call"]


def test_unknown_group_rejected(env) -> None:
    res = post(env, groups=["no-such-group"])
    assert (res.status_code, res.json()["detail"]["reason"]) == (400, "unknown_group")


@pytest.mark.parametrize(
    "body",
    [{"title": ""}, {"title": "x" * 121}, {"body": ""}, {"body": "x" * 5001}, {"authorName": "Someone"},
     {"createdAt": "2020-01-01"}, {"id": "mine"}],
)
def test_bad_input_rejected(env, body: dict) -> None:
    assert post(env, **body).status_code == 422
    assert env["announcements"].list_all() == []


def test_edit_keeps_author_and_marks_updated(env) -> None:
    a = post(env).json()
    res = client.patch(f"/api/announcements/{a['id']}", headers=env["admin"], json={"body": "Black, no tie."})
    b = res.json()
    assert (b["body"], b["title"], b["authorName"], b["createdAt"]) == ("Black, no tie.", a["title"], "Admin", a["createdAt"])
    assert b["updatedAt"] is not None
    assert client.patch(f"/api/announcements/{a['id']}", headers=env["admin"], json={"title": None}).status_code == 422


def test_delete(env) -> None:
    a = post(env).json()
    assert client.delete(f"/api/announcements/{a['id']}", headers=env["admin"]).status_code == 204
    assert client.get(f"/api/announcements/{a['id']}", headers=env["member"]).status_code == 404


def test_deleting_the_only_group_keeps_the_post_private(env) -> None:
    """An empty list means everyone, so a post whose only group is deleted must not become public."""
    quartet, tags = make_group(env, "Quartet"), make_group(env, "Tags")
    only = post(env, title="Only quartet", groups=[quartet]).json()
    both = post(env, title="Both", groups=[quartet, tags]).json()
    assert client.delete(f"/api/groups/{quartet}", headers=env["admin"]).status_code == 204
    assert env["announcements"].get(only["id"])["groups"] == [quartet]
    assert env["announcements"].get(both["id"])["groups"] == [tags]
    assert titles(env) == []


def test_erased_author_is_forgotten_but_post_stays(env) -> None:
    owner = add_member(env["members"], OWNER_EMAIL, "owner")
    a = post(env).json()
    exported = client.get("/api/me/export", headers=env["admin"]).json()["announcements"]
    assert [x["id"] for x in exported] == [a["id"]]
    assert client.delete("/api/members/google:sub-admin@example.com", headers=owner).status_code == 204
    left = client.get(f"/api/announcements/{a['id']}", headers=env["member"]).json()
    assert (left["title"], left["authorName"]) == ("Concert dress", None)
    assert "authorId" not in env["announcements"].get(a["id"])
