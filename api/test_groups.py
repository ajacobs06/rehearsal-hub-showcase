import pytest
from fastapi.testclient import TestClient

from main import app
from test_main import OWNER_EMAIL, add_member, principal
from test_rehearsals import make_rehearsal, rsvp
from test_songs import env, make_song  # noqa: F401  (env is a fixture)

client = TestClient(app)
MEMBER_ID = "google:sub-m@example.com"


@pytest.fixture
def owner(env) -> dict:
    return add_member(env["members"], OWNER_EMAIL, "owner")


def set_groups(env, who: dict, member_id: str, groups: list[str]):
    return client.patch(f"/api/members/{member_id}", headers=who, json={"groups": groups})


# ---------- Committee = admin ----------


def test_committee_makes_admin_and_leaving_removes_it(env, owner) -> None:
    assert set_groups(env, owner, MEMBER_ID, ["committee", "open"]).json()["role"] == "admin"
    assert client.get("/api/members", headers=env["member"]).status_code == 200  # now an admin
    assert set_groups(env, owner, MEMBER_ID, ["open"]).json()["role"] == "member"
    assert client.get("/api/members", headers=env["member"]).status_code == 403


def test_only_owners_change_committee(env) -> None:
    res = set_groups(env, env["admin"], MEMBER_ID, ["committee"])
    assert res.status_code == 403
    assert env["members"].get(MEMBER_ID)["role"] == "member"


def test_admin_can_change_other_groups(env) -> None:
    res = set_groups(env, env["admin"], MEMBER_ID, ["auditioned"])
    assert (res.status_code, res.json()["groups"], res.json()["role"]) == (200, ["auditioned"], "member")


def test_owner_can_hand_over_ownership(env, owner) -> None:
    res = client.patch(f"/api/members/{MEMBER_ID}", headers=owner, json={"owner": True})
    assert res.json()["role"] == "owner"
    res = client.patch(f"/api/members/{MEMBER_ID}", headers=owner, json={"owner": False})
    assert res.json()["role"] == "member"


@pytest.mark.parametrize(
    "body", [{"groups": ["nonexistent"]}, {"groups": None}, {"owner": None}, {"role": "admin"}, {"groups": "open"}]
)
def test_member_update_rejects_bad_groups(env, owner, body: dict) -> None:
    res = client.patch(f"/api/members/{MEMBER_ID}", headers=owner, json=body)
    assert res.status_code in (400, 422)
    assert env["members"].get(MEMBER_ID)["role"] == "member"


def test_invite_with_groups(env, owner) -> None:
    res = client.post("/api/members", headers=env["admin"], json={"email": "q@example.com", "name": "Q", "groups": ["open"]})
    assert res.json()["member"]["groups"] == ["open"]
    bad = client.post("/api/members", headers=env["admin"], json={"email": "z@example.com", "name": "Z", "groups": ["nope"]})
    assert bad.status_code == 400
    # The claimed member keeps the invite's groups.
    me = client.get("/api/me", headers=principal("q@example.com", sub="q1")).json()
    assert me["groups"] == ["open"]


def test_existing_admins_join_committee(env) -> None:
    # Docs created before groups existed have no "groups" field.
    env["members"].docs["google:sub-admin@example.com"].pop("groups", None)
    me = client.get("/api/me", headers=env["admin"]).json()
    assert (me["groups"], me["role"]) == (["committee"], "admin")


# ---------- Quartets ----------


def test_quartet_lifecycle(env, owner) -> None:
    q = client.post("/api/groups", headers=env["admin"], json={"name": "Four on the Floor"}).json()
    assert q["admin"] is False
    assert client.patch(f"/api/groups/{q['id']}", headers=env["admin"], json={"name": "Chord Cutters"}).json()["name"] == "Chord Cutters"
    res = client.put(f"/api/groups/{q['id']}/members", headers=env["admin"], json={"memberIds": [MEMBER_ID]})
    assert res.json()["memberCount"] == 1
    assert env["members"].get(MEMBER_ID)["groups"] == [q["id"]]
    r = make_rehearsal(env, groups=[q["id"]])
    listed = {g["id"]: g["memberCount"] for g in client.get("/api/groups", headers=env["member"]).json()}
    assert listed[q["id"]] == 1 and {"auditioned", "open", "committee"} <= listed.keys()

    assert client.delete(f"/api/groups/{q['id']}", headers=env["admin"]).status_code == 204
    assert env["members"].get(MEMBER_ID)["groups"] == []
    assert env["rehearsals"].get(r["id"])["groups"] == []


def test_members_cannot_manage_groups(env) -> None:
    assert client.post("/api/groups", headers=env["member"], json={"name": "Mine"}).status_code == 403
    assert client.put("/api/groups/open/members", headers=env["member"], json={"memberIds": []}).status_code == 403


def test_default_groups_are_ordinary_groups(env) -> None:
    listed = [(g["id"], g["name"], g["admin"]) for g in client.get("/api/groups", headers=env["admin"]).json()]
    assert listed == [("auditioned", "Auditioned chorus", False), ("open", "Open chorus", False), ("committee", "Committee", True)]
    assert client.patch("/api/groups/open", headers=env["admin"], json={"name": "Community chorus"}).json()["name"] == "Community chorus"
    assert client.delete("/api/groups/auditioned", headers=env["admin"]).status_code == 204
    # Deleted defaults are not recreated.
    ids = [g["id"] for g in client.get("/api/groups", headers=env["admin"]).json()]
    assert ids == ["open", "committee"]


def test_admin_access_changes_are_owner_only(env) -> None:
    assert client.delete("/api/groups/committee", headers=env["admin"]).status_code == 403
    assert client.patch("/api/groups/open", headers=env["admin"], json={"admin": True}).status_code == 403
    assert client.post("/api/groups", headers=env["admin"], json={"name": "Board", "admin": True}).status_code == 403
    assert client.patch("/api/groups/committee", headers=env["admin"], json={"name": "Exec"}).status_code == 200


def test_admin_access_setting_promotes_and_demotes(env, owner) -> None:
    set_groups(env, env["admin"], MEMBER_ID, ["open"])
    assert client.patch("/api/groups/open", headers=owner, json={"admin": True}).json()["admin"] is True
    assert env["members"].get(MEMBER_ID)["role"] == "admin"
    client.patch("/api/groups/open", headers=owner, json={"admin": False})
    assert env["members"].get(MEMBER_ID)["role"] == "member"


def test_deleting_admin_group_demotes_but_keeps_owner(env, owner) -> None:
    client.get("/api/me", headers=owner)  # owner joins committee via migration
    admin_id = "google:sub-admin@example.com"
    env["members"].upsert({**env["members"].get(admin_id), "groups": ["committee"]})
    assert client.delete("/api/groups/committee", headers=owner).status_code == 204
    assert env["members"].get(admin_id)["role"] == "member"
    assert env["members"].get(f"google:sub-{OWNER_EMAIL}")["role"] == "owner"


@pytest.mark.parametrize("body", [{"name": None}, {"admin": None}, {"name": ""}, {"kind": "fixed"}])
def test_group_update_rejects_bad_input(env, owner, body: dict) -> None:
    assert client.patch("/api/groups/open", headers=owner, json=body).status_code == 422



def test_group_members_endpoint_guards_committee(env, owner) -> None:
    res = client.put("/api/groups/committee/members", headers=env["admin"], json={"memberIds": ["google:sub-admin@example.com", MEMBER_ID]})
    assert res.status_code == 403
    assert env["members"].get(MEMBER_ID)["role"] == "member"
    res = client.put("/api/groups/committee/members", headers=owner, json={"memberIds": [MEMBER_ID]})
    assert res.status_code == 200
    assert env["members"].get(MEMBER_ID)["role"] == "admin"
    assert env["members"].get("google:sub-admin@example.com")["role"] == "member"  # left the committee


def test_group_members_rejects_unknown_member(env) -> None:
    res = client.put("/api/groups/open/members", headers=env["admin"], json={"memberIds": ["ghost"]})
    assert res.status_code == 400


# ---------- Rehearsal visibility ----------


def test_rehearsal_hidden_from_other_groups(env) -> None:
    r = make_rehearsal(env, groups=["auditioned"])
    assert client.get("/api/rehearsals", headers=env["member"]).json() == []
    assert client.get(f"/api/rehearsals/{r['id']}", headers=env["member"]).status_code == 404
    assert rsvp(env, r["id"], "yes").status_code == 404
    set_groups(env, env["admin"], MEMBER_ID, ["auditioned"])
    assert [x["id"] for x in client.get("/api/rehearsals", headers=env["member"]).json()] == [r["id"]]
    assert rsvp(env, r["id"], "yes").status_code == 200


def test_rehearsal_for_everyone_when_no_groups(env) -> None:
    r = make_rehearsal(env)
    assert [x["id"] for x in client.get("/api/rehearsals", headers=env["member"]).json()] == [r["id"]]


def test_rehearsal_counts_only_its_audience(env) -> None:
    set_groups(env, env["admin"], MEMBER_ID, ["open"])
    r = make_rehearsal(env, groups=["open"])
    view = client.get(f"/api/rehearsals/{r['id']}", headers=env["admin"]).json()
    # The admin can see it but isn't in the open chorus, so only the member is expected.
    assert view["counts"]["noReply"] == 1
    assert [a["name"] for a in view["attendees"]] == ["M"]


def test_rehearsal_rejects_unknown_group(env) -> None:
    res = client.post(
        "/api/rehearsals", headers=env["admin"], json={"start": "2030-01-01T19:00:00+00:00", "venue": "X", "groups": ["nope"]}
    )
    assert res.status_code == 400


def test_songs_stay_visible_to_everyone(env) -> None:
    make_song(env, title="Lida Rose")
    set_groups(env, env["admin"], MEMBER_ID, ["open"])
    assert [s["title"] for s in client.get("/api/songs", headers=env["member"]).json()] == ["Lida Rose"]


def test_admin_default_list_is_their_own_view(env) -> None:
    other = make_rehearsal(env, groups=["auditioned"])
    everyone = make_rehearsal(env)
    mine = [r["id"] for r in client.get("/api/rehearsals", headers=env["admin"]).json()]
    assert mine == [everyone["id"]]
    every = {r["id"] for r in client.get("/api/rehearsals?scope=all", headers=env["admin"]).json()}
    assert every == {other["id"], everyone["id"]}
    # Admins can still open any rehearsal to manage it.
    assert client.get(f"/api/rehearsals/{other['id']}", headers=env["admin"]).status_code == 200


def test_members_cannot_list_all_rehearsals(env) -> None:
    assert client.get("/api/rehearsals?scope=all", headers=env["member"]).status_code == 403
