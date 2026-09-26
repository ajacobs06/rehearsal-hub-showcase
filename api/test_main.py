import base64
import json

import pytest
from fastapi.testclient import TestClient

from auth import CLAIM_EMAIL, CLAIM_ID
from mailer import get_mailer
from main import app
from store import InMemoryMemberStore, get_store

OWNER_EMAIL = "owner@example.com"


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_invite(self, to: str, name: str, invited_by: str) -> bool:
        self.sent.append(to)
        return True


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> InMemoryMemberStore:
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")
    monkeypatch.setenv("BOOTSTRAP_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.delenv("DEV_USER_EMAIL", raising=False)
    s = InMemoryMemberStore()
    app.dependency_overrides[get_store] = lambda: s
    yield s
    app.dependency_overrides.clear()


@pytest.fixture
def mailer() -> FakeMailer:
    m = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: m
    return m


client = TestClient(app)


def principal(email: str, sub: str | None = None, verified: bool = True) -> dict[str, str]:
    claims = [
        {"typ": CLAIM_ID, "val": sub or f"sub-{email}"},
        {"typ": CLAIM_EMAIL, "val": email},
        {"typ": "name", "val": email.split("@")[0].title()},
        {"typ": "email_verified", "val": str(verified).lower()},
    ]
    raw = json.dumps({"auth_typ": "google", "claims": claims}).encode()
    return {"X-MS-CLIENT-PRINCIPAL": base64.b64encode(raw).decode()}


def add_member(store: InMemoryMemberStore, email: str, role: str) -> dict[str, str]:
    headers = principal(email)
    store.upsert(
        {
            "id": f"google:sub-{email}",
            "email": email,
            "name": email.split("@")[0].title(),
            "part": "lead",
            "role": role,
            "status": "active",
            "createdAt": "2026-09-26T00:00:00+00:00",
        }
    )
    return headers


def test_health() -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# ---------- Sign-in ----------


def test_me_requires_sign_in(store: InMemoryMemberStore) -> None:
    assert client.get("/api/me").status_code == 401


def test_principal_header_ignored_when_easy_auth_disabled(
    store: InMemoryMemberStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WEBSITE_AUTH_ENABLED")
    add_member(store, "admin@example.com", "admin")
    assert client.get("/api/me", headers=principal("admin@example.com")).status_code == 401


def test_malformed_principal_is_unauthenticated(store: InMemoryMemberStore) -> None:
    assert client.get("/api/me", headers={"X-MS-CLIENT-PRINCIPAL": "not-base64!"}).status_code == 401


def test_unverified_email_is_unauthenticated(store: InMemoryMemberStore) -> None:
    res = client.get("/api/me", headers=principal(OWNER_EMAIL, verified=False))
    assert res.status_code == 401


def test_uninvited_user_is_rejected(store: InMemoryMemberStore) -> None:
    res = client.get("/api/me", headers=principal("stranger@example.com"))
    assert res.status_code == 403
    assert res.json()["detail"] == {"reason": "not_invited", "email": "stranger@example.com"}


def test_bootstrap_owner_on_first_sign_in(store: InMemoryMemberStore) -> None:
    res = client.get("/api/me", headers=principal("Owner@Example.com"))
    assert res.status_code == 200
    assert res.json()["role"] == "owner"
    assert res.json()["id"] == "google:sub-Owner@Example.com"


def test_invite_is_claimed_on_first_sign_in(store: InMemoryMemberStore, mailer: FakeMailer) -> None:
    admin = add_member(store, "admin@example.com", "admin")
    client.post("/api/members", headers=admin, json={"email": "New@Example.com", "name": "New", "part": "bass"})

    res = client.get("/api/me", headers=principal("new@example.com", sub="g-123"))
    assert res.status_code == 200
    body = res.json()
    assert (body["id"], body["status"], body["part"]) == ("google:g-123", "active", "bass")
    assert [d["id"] for d in store.list_all() if d["email"] == "new@example.com"] == ["google:g-123"]


def test_update_me_sets_part_but_not_role(store: InMemoryMemberStore) -> None:
    me = add_member(store, "m@example.com", "member")
    assert client.patch("/api/me", headers=me, json={"part": "tenor"}).json()["part"] == "tenor"
    assert client.patch("/api/me", headers=me, json={"role": "owner"}).status_code == 400


# ---------- Role enforcement ----------


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/members"), ("post", "/api/members"), ("patch", "/api/members/x"), ("delete", "/api/members/x")],
)
def test_member_cannot_use_admin_endpoints(store: InMemoryMemberStore, method: str, path: str) -> None:
    member = add_member(store, "m@example.com", "member")
    body = {"email": "x@example.com", "name": "X"} if method in ("post", "patch") else None
    res = client.request(method, path, headers=member, json=body)
    assert res.status_code == 403


def test_admin_lists_and_invites(store: InMemoryMemberStore, mailer: FakeMailer) -> None:
    admin = add_member(store, "admin@example.com", "admin")
    res = client.post("/api/members", headers=admin, json={"email": "a@example.com", "name": "A"})
    assert res.status_code == 201
    assert res.json()["emailed"] is True
    assert mailer.sent == ["a@example.com"]
    emails = [m["email"] for m in client.get("/api/members", headers=admin).json()]
    assert emails == ["admin@example.com", "a@example.com"]


def test_duplicate_invite_conflicts(store: InMemoryMemberStore, mailer: FakeMailer) -> None:
    admin = add_member(store, "admin@example.com", "admin")
    res = client.post("/api/members", headers=admin, json={"email": "ADMIN@example.com", "name": "Dup"})
    assert res.status_code == 409


def test_admin_cannot_grant_admin_but_owner_can(store: InMemoryMemberStore, mailer: FakeMailer) -> None:
    admin = add_member(store, "admin@example.com", "admin")
    owner = add_member(store, OWNER_EMAIL, "owner")
    invite = {"email": "b@example.com", "name": "B", "role": "admin"}
    assert client.post("/api/members", headers=admin, json=invite).status_code == 403
    assert client.post("/api/members", headers=owner, json=invite).status_code == 201


def test_admin_cannot_modify_other_admins(store: InMemoryMemberStore) -> None:
    admin = add_member(store, "admin@example.com", "admin")
    add_member(store, "admin2@example.com", "admin")
    target = "/api/members/google:sub-admin2@example.com"
    assert client.patch(target, headers=admin, json={"part": "bass"}).status_code == 403
    assert client.delete(target, headers=admin).status_code == 403


def test_admin_manages_members(store: InMemoryMemberStore) -> None:
    admin = add_member(store, "admin@example.com", "admin")
    add_member(store, "m@example.com", "member")
    target = "/api/members/google:sub-m@example.com"
    assert client.patch(target, headers=admin, json={"part": "bari"}).json()["part"] == "bari"
    assert client.patch(target, headers=admin, json={"role": "admin"}).status_code == 403
    assert client.delete(target, headers=admin).status_code == 204
    assert store.get("google:sub-m@example.com") is None


def test_owner_cannot_change_own_role_or_delete_self(store: InMemoryMemberStore) -> None:
    owner = add_member(store, OWNER_EMAIL, "owner")
    me = f"/api/members/google:sub-{OWNER_EMAIL}"
    assert client.patch(me, headers=owner, json={"role": "member"}).status_code == 400
    assert client.delete(me, headers=owner).status_code == 400
