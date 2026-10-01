from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from main import app
from test_main import OWNER_EMAIL, add_member
from test_songs import MP3, PDF, env, make_song, upload  # noqa: F401  (env is a fixture)

client = TestClient(app)
MEMBER_ID = "google:sub-m@example.com"


def at(hours: float) -> str:
    """An ISO time `hours` from now, with a UK summer-time offset."""
    t = datetime.now(timezone.utc) + timedelta(hours=hours)
    return t.astimezone(timezone(timedelta(hours=1))).isoformat(timespec="seconds")


def make_rehearsal(env, **body) -> dict:
    payload = {"start": at(48), "end": at(50), "venue": "Bramall Music Building", **body}
    res = client.post("/api/rehearsals", headers=env["admin"], json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def rsvp(env, rid: str, response, who: str = "member"):
    return client.put(f"/api/rehearsals/{rid}/rsvp", headers=env[who], json={"response": response})


# ---------- Permissions ----------


def test_rehearsals_require_sign_in(env) -> None:
    assert client.get("/api/rehearsals").status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/rehearsals", {"start": "2030-01-01T19:00:00+00:00", "venue": "X"}),
        ("patch", "/api/rehearsals/{id}", {"venue": "Hijacked"}),
        ("delete", "/api/rehearsals/{id}", None),
    ],
)
def test_member_cannot_manage_rehearsals(env, method: str, path: str, body) -> None:
    r = make_rehearsal(env)
    res = client.request(method, path.format(id=r["id"]), headers=env["member"], json=body)
    assert res.status_code == 403
    assert env["rehearsals"].get(r["id"])["venue"] == "Bramall Music Building"


# ---------- Validation ----------


@pytest.mark.parametrize(
    "body",
    [
        {"start": "2030-01-01T19:00:00", "venue": "X"},  # no timezone
        {"start": "2030-01-01T19:00:00+00:00", "end": "2030-01-01T18:00:00+00:00", "venue": "X"},
        {"start": "2030-01-01T19:00:00+00:00", "end": "2030-01-02T19:00:00+00:00", "venue": "X"},
        {"start": "2030-01-01T19:00:00+00:00", "venue": "   "},
        {"start": "2030-01-01T19:00:00+00:00", "venue": "X", "notes": "x" * 2001},
        {"start": "2030-01-01T19:00:00+00:00", "venue": "X", "songIds": [f"s{i}" for i in range(31)]},
        {"start": "2030-01-01T19:00:00+00:00", "venue": "X", "rsvps": {"forged": {"response": "yes"}}},
        {"start": "not a date", "venue": "X"},
    ],
)
def test_create_rejects_bad_input(env, body: dict) -> None:
    assert client.post("/api/rehearsals", headers=env["admin"], json=body).status_code == 422
    assert env["rehearsals"].list_all() == []


def test_create_rejects_unknown_song(env) -> None:
    res = client.post(
        "/api/rehearsals", headers=env["admin"], json={"start": at(48), "venue": "X", "songIds": ["nope"]}
    )
    assert res.status_code == 400
    assert res.json()["detail"]["reason"] == "unknown_song"


@pytest.mark.parametrize("body", [{"venue": None}, {"start": None}, {"songIds": None}, {"rsvps": {}}])
def test_update_rejects_bad_input(env, body: dict) -> None:
    r = make_rehearsal(env)
    assert client.patch(f"/api/rehearsals/{r['id']}", headers=env["admin"], json=body).status_code == 422


def test_update_rejects_end_before_existing_start(env) -> None:
    r = make_rehearsal(env)
    res = client.patch(f"/api/rehearsals/{r['id']}", headers=env["admin"], json={"end": at(1)})
    assert res.status_code == 422


def test_update_can_clear_end_and_notes(env) -> None:
    r = make_rehearsal(env, notes="Bring water")
    res = client.patch(f"/api/rehearsals/{r['id']}", headers=env["admin"], json={"end": None, "notes": None})
    assert (res.json()["end"], res.json()["notes"]) == (None, None)


# ---------- Upcoming and past ----------


def test_upcoming_and_past(env) -> None:
    later = make_rehearsal(env, start=at(72), end=at(74), venue="Later")
    sooner = make_rehearsal(env, start=at(24), end=at(26), venue="Sooner")
    ongoing = make_rehearsal(env, start=at(-2), end=None, venue="Started 2h ago")
    done = make_rehearsal(env, start=at(-30), end=at(-28), venue="Last week")
    upcoming = [r["venue"] for r in client.get("/api/rehearsals", headers=env["member"]).json()]
    assert upcoming == ["Started 2h ago", "Sooner", "Later"]
    past = [r["venue"] for r in client.get("/api/rehearsals?when=past", headers=env["member"]).json()]
    assert past == ["Last week"]
    assert {later["id"], sooner["id"], ongoing["id"], done["id"]}


def test_rsvp_closed_after_rehearsal(env) -> None:
    r = make_rehearsal(env, start=at(-5), end=at(-3))
    res = rsvp(env, r["id"], "yes")
    assert res.status_code == 400
    assert res.json()["detail"]["reason"] == "rsvp_closed"


# ---------- RSVP ----------


def test_rsvp_set_change_withdraw(env) -> None:
    r = make_rehearsal(env)
    assert rsvp(env, r["id"], "yes").json()["myRsvp"] == "yes"
    assert rsvp(env, r["id"], "maybe").json()["myRsvp"] == "maybe"
    res = rsvp(env, r["id"], None)
    assert res.json()["myRsvp"] is None
    assert env["rehearsals"].get(r["id"])["rsvps"] == {}


@pytest.mark.parametrize("body", [{"response": "definitely"}, {}, {"response": "yes", "memberId": "someone-else"}])
def test_rsvp_rejects_bad_input(env, body: dict) -> None:
    r = make_rehearsal(env)
    res = client.put(f"/api/rehearsals/{r['id']}/rsvp", headers=env["member"], json=body)
    assert res.status_code == 422
    assert env["rehearsals"].get(r["id"])["rsvps"] == {}


def test_members_see_only_their_own_reply(env) -> None:
    r = make_rehearsal(env)
    rsvp(env, r["id"], "yes", who="admin")
    rsvp(env, r["id"], "maybe")
    views = [
        client.get(f"/api/rehearsals/{r['id']}", headers=env["member"]).json(),
        client.get("/api/rehearsals", headers=env["member"]).json()[0],
        rsvp(env, r["id"], "yes").json(),
    ]
    for view in views:
        assert view["counts"] is None and view["attendees"] is None and view["songParts"] is None
    assert views[1]["myRsvp"] == "maybe" and views[2]["myRsvp"] == "yes"


def test_admin_sees_totals(env) -> None:
    r = make_rehearsal(env)
    rsvp(env, r["id"], "yes")
    view = client.get(f"/api/rehearsals/{r['id']}", headers=env["admin"]).json()
    assert view["counts"] == {"yes": 1, "maybe": 0, "no": 0, "noReply": 1}


def test_admin_sees_attendees_and_parts_by_song(env) -> None:
    medley = make_song(env, title="Hunchback Medley")
    lida = make_song(env, title="Lida Rose")
    r = make_rehearsal(env, songIds=[medley["id"], lida["id"]])
    client.put(f"/api/songs/{medley['id']}/my-part", headers=env["member"], json={"part": "bass"})
    rsvp(env, r["id"], "yes")
    rsvp(env, r["id"], "maybe", who="admin")
    view = client.get(f"/api/rehearsals/{r['id']}", headers=env["admin"]).json()
    assert {a["name"]: a["response"] for a in view["attendees"]} == {"Admin": "maybe", "M": "yes"}
    parts = {sp["title"]: sp["parts"] for sp in view["songParts"]}
    # The member sings bass on the medley but their usual lead on Lida Rose.
    assert parts["Hunchback Medley"] == {"bass": {"yes": 1, "maybe": 0}, "lead": {"yes": 0, "maybe": 1}}
    assert parts["Lida Rose"] == {"lead": {"yes": 1, "maybe": 1}}


def test_admin_edit_keeps_rsvps(env) -> None:
    r = make_rehearsal(env)
    rsvp(env, r["id"], "yes")
    res = client.patch(f"/api/rehearsals/{r['id']}", headers=env["admin"], json={"venue": "Elgar Concert Hall"})
    assert res.json()["venue"] == "Elgar Concert Hall"
    assert env["rehearsals"].get(r["id"])["rsvps"][MEMBER_ID]["response"] == "yes"


def test_song_view_shows_my_part_state_and_track(env) -> None:
    song = make_song(env)
    upload(env, song["id"], "lead", MP3)
    client.put(f"/api/songs/{song['id']}/my-state", headers=env["member"], json={"state": "learning"})
    retired = make_song(env, title="Old", status="retired")
    r = make_rehearsal(env, songIds=[song["id"], retired["id"]])
    songs = client.get(f"/api/rehearsals/{r['id']}", headers=env["member"]).json()["songs"]
    assert [(s["title"], s["myPart"], s["myState"], s["hasMyTrack"]) for s in songs] == [
        ("Lida Rose", "lead", "learning", True)
    ]


# ---------- Cleanup ----------


def test_deleting_song_removes_it_from_plans(env) -> None:
    song = make_song(env)
    r = make_rehearsal(env, songIds=[song["id"]])
    client.delete(f"/api/songs/{song['id']}", headers=env["admin"])
    assert env["rehearsals"].get(r["id"])["songIds"] == []


def test_removing_member_removes_their_rsvps(env) -> None:
    r = make_rehearsal(env)
    rsvp(env, r["id"], "yes")
    owner = add_member(env["members"], OWNER_EMAIL, "owner")
    client.delete(f"/api/members/{MEMBER_ID}", headers=owner)
    assert env["rehearsals"].get(r["id"])["rsvps"] == {}


def test_delete_rehearsal(env) -> None:
    r = make_rehearsal(env)
    assert client.delete(f"/api/rehearsals/{r['id']}", headers=env["admin"]).status_code == 204
    assert client.get(f"/api/rehearsals/{r['id']}", headers=env["member"]).status_code == 404


def test_rehearsal_songs_report_score(env) -> None:
    with_score, without = make_song(env, title="Lida Rose"), make_song(env, title="Hunchback Medley")
    upload(env, with_score["id"], "score", PDF)
    r = make_rehearsal(env, songIds=[with_score["id"], without["id"]])
    songs = {s["title"]: s["hasScore"] for s in client.get(f"/api/rehearsals/{r['id']}", headers=env["member"]).json()["songs"]}
    assert songs == {"Lida Rose": True, "Hunchback Medley": False}
