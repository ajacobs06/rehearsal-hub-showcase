"""Sign-in identity rules (security audit M-1, L-5)."""
import base64
import json

import pytest

from auth import CLAIM_EMAIL, CLAIM_ID
from store import InMemoryStore
from test_main import OWNER_EMAIL, add_member, client, principal, store  # noqa: F401  (store is a fixture)


def raw_principal(email: str, idp: str | None = "google", sub: str = "sub-x", verified: str | None = "true"):
    claims = [{"typ": CLAIM_ID, "val": sub}, {"typ": CLAIM_EMAIL, "val": email}]
    if verified is not None:
        claims.append({"typ": "email_verified", "val": verified})
    data = {"claims": claims} | ({"auth_typ": idp} if idp else {})
    return {"X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(data).encode()).decode()}


@pytest.mark.parametrize("verified", [None, "false", "False", "", "yes"])
def test_email_must_be_verified(store: InMemoryStore, verified) -> None:
    """A missing claim used to count as verified."""
    res = client.get("/api/me", headers=raw_principal(OWNER_EMAIL, verified=verified))
    assert res.status_code == 401
    assert store.list_all() == []


def test_verified_true_in_any_case_is_accepted(store: InMemoryStore) -> None:
    assert client.get("/api/me", headers=raw_principal(OWNER_EMAIL, verified="True")).status_code == 200


@pytest.mark.parametrize("idp", ["github", "aad", "twitter", "unknown", None])
def test_only_google_sign_in_is_accepted(store: InMemoryStore, idp) -> None:
    """Even with a verified email claim, other providers aren't trusted for email matching."""
    res = client.get("/api/me", headers=raw_principal(OWNER_EMAIL, idp=idp))
    assert res.status_code == 401
    assert store.list_all() == []


def test_other_provider_cannot_claim_an_invite(store: InMemoryStore) -> None:
    owner = add_member(store, OWNER_EMAIL, "owner")
    assert client.post("/api/members", headers=owner, json={"email": "new@example.com", "name": "New"}).status_code == 201
    assert client.get("/api/me", headers=raw_principal("new@example.com", idp="github")).status_code == 401
    assert client.get("/api/me", headers=raw_principal("new@example.com", verified=None)).status_code == 401
    # The real invitee still can.
    assert client.get("/api/me", headers=principal("new@example.com")).json()["status"] == "active"


def test_bootstrap_owner_on_an_empty_database(store: InMemoryStore) -> None:
    res = client.get("/api/me", headers=principal(OWNER_EMAIL))
    assert res.status_code == 200
    assert res.json()["role"] == "owner"


def test_bootstrap_does_nothing_once_an_owner_exists(store: InMemoryStore) -> None:
    """A second Google account with the owner's email (any case) used to become another owner."""
    assert client.get("/api/me", headers=principal(OWNER_EMAIL)).json()["role"] == "owner"
    for email, sub in ((OWNER_EMAIL, "other-sub"), (OWNER_EMAIL.upper(), "third-sub")):
        res = client.get("/api/me", headers=raw_principal(email, sub=sub))
        assert res.status_code == 403
        assert res.json()["detail"]["reason"] == "not_invited"
    assert [m["role"] for m in store.list_all()] == ["owner"]


def test_bootstrap_does_nothing_when_another_account_is_owner(store: InMemoryStore) -> None:
    add_member(store, "someone.else@example.com", "owner")
    assert client.get("/api/me", headers=principal(OWNER_EMAIL)).status_code == 403


# ---------- Local dev sign-in ----------


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch, store: InMemoryStore) -> pytest.MonkeyPatch:
    """A machine with no App Service variables at all."""
    for key in [k for k in __import__("os").environ if k.startswith("WEBSITE_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("DEV_USER_EMAIL", OWNER_EMAIL)
    return monkeypatch


def test_dev_auth_needs_the_explicit_flag(local: pytest.MonkeyPatch) -> None:
    assert client.get("/api/me").status_code == 401
    local.setenv("ALLOW_DEV_AUTH", "1")
    assert client.get("/api/me").json()["id"] == f"dev:{OWNER_EMAIL}"


@pytest.mark.parametrize("var", ["WEBSITE_SITE_NAME", "WEBSITE_INSTANCE_ID", "WEBSITE_HOSTNAME"])
def test_dev_auth_is_refused_on_app_service(local: pytest.MonkeyPatch, var: str) -> None:
    local.setenv("ALLOW_DEV_AUTH", "1")
    local.setenv(var, "rehearsal-hub")
    assert client.get("/api/me").status_code == 401


def test_dev_auth_is_ignored_when_easy_auth_is_on(local: pytest.MonkeyPatch) -> None:
    local.setenv("ALLOW_DEV_AUTH", "1")
    local.setenv("WEBSITE_AUTH_ENABLED", "True")
    assert client.get("/api/me").status_code == 401
