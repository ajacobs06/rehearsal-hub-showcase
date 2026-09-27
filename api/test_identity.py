"""Sign-in identity rules (security audit M-1, L-5)."""
import base64
import json

import pytest

import entra as entra_module
from auth import CLAIM_EMAIL, CLAIM_ID, CLAIM_OID, CLAIM_TID
from entra import EntraDeleteFailed, GraphDirectory, entra_object_id, get_directory
from main import app
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


@pytest.mark.parametrize("idp", ["github", "twitter", "facebook", "unknown", None])
def test_only_google_and_entra_sign_in_are_accepted(store: InMemoryStore, idp) -> None:
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


# ---------- Entra External ID (email and password) ----------

TENANT = "11111111-2222-3333-4444-555555555555"


def entra_principal(email: str, tenant: str | None = TENANT, oid: str | None = "oid-1", long_names: bool = True):
    claims = [{"typ": CLAIM_ID, "val": "pairwise-sub"}, {"typ": CLAIM_EMAIL if long_names else "email", "val": email}]
    if oid is not None:
        claims.append({"typ": CLAIM_OID if long_names else "oid", "val": oid})
    if tenant is not None:
        claims.append({"typ": CLAIM_TID if long_names else "tid", "val": tenant})
    data = {"auth_typ": "aad", "claims": claims}
    return {"X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(data).encode()).decode()}


@pytest.fixture
def entra(monkeypatch: pytest.MonkeyPatch, store: InMemoryStore) -> InMemoryStore:
    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT)
    return store


def test_welcome_page_learns_whether_email_sign_in_is_on(store: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    assert client.get("/api/me").json()["detail"]["emailSignIn"] is False
    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT)
    assert client.get("/api/me").json()["detail"]["emailSignIn"] is True


@pytest.mark.parametrize("long_names", [True, False])
def test_entra_account_claims_an_invite(entra: InMemoryStore, long_names: bool) -> None:
    owner = add_member(entra, OWNER_EMAIL, "owner")
    assert client.post("/api/members", headers=owner, json={"email": "any@hotmail.co.uk", "name": "Any"}).status_code == 201
    me = client.get("/api/me", headers=entra_principal("Any@Hotmail.co.uk", long_names=long_names)).json()
    assert me["id"] == "aad:oid-1"
    assert me["status"] == "active"


def test_entra_uninvited_email_is_not_let_in(entra: InMemoryStore) -> None:
    add_member(entra, OWNER_EMAIL, "owner")
    res = client.get("/api/me", headers=entra_principal("stranger@example.com"))
    assert res.status_code == 403
    assert res.json()["detail"]["reason"] == "not_invited"


@pytest.mark.parametrize("tenant", [None, "", "99999999-2222-3333-4444-555555555555"])
def test_entra_from_another_tenant_is_refused(entra: InMemoryStore, tenant) -> None:
    """Other tenants' admins can give an account any email, so only ours is trusted."""
    assert client.get("/api/me", headers=entra_principal(OWNER_EMAIL, tenant=tenant)).status_code == 401
    assert entra.list_all() == []


def test_entra_is_refused_when_no_tenant_is_configured(store: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    assert client.get("/api/me", headers=entra_principal(OWNER_EMAIL)).status_code == 401


def test_entra_needs_an_object_id(entra: InMemoryStore) -> None:
    """The per-app `sub` is not used as the member id; the object id is."""
    assert client.get("/api/me", headers=entra_principal(OWNER_EMAIL, oid=None)).status_code == 401


# ---------- Deleting Entra accounts (erasure, uninvited sign-ups) ----------


class FakeDirectory:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.fail = False

    def delete_user(self, object_id: str) -> None:
        if self.fail:
            raise EntraDeleteFailed("Graph is down")
        self.deleted.append(object_id)


@pytest.fixture
def directory(entra: InMemoryStore) -> FakeDirectory:
    d = FakeDirectory()
    app.dependency_overrides[get_directory] = lambda: d
    return d


def invite_and_sign_in(store: InMemoryStore, email: str = "any@hotmail.co.uk") -> tuple[dict, dict]:
    owner = add_member(store, OWNER_EMAIL, "owner")
    assert client.post("/api/members", headers=owner, json={"email": email, "name": "Any"}).status_code == 201
    member = entra_principal(email)
    assert client.get("/api/me", headers=member).json()["id"] == "aad:oid-1"
    return owner, member


def test_uninvited_email_sign_up_is_deleted(directory: FakeDirectory, entra: InMemoryStore) -> None:
    add_member(entra, OWNER_EMAIL, "owner")
    res = client.get("/api/me", headers=entra_principal("stranger@example.com"))
    assert res.json()["detail"]["reason"] == "not_invited"
    assert directory.deleted == ["oid-1"]


def test_uninvited_sign_up_still_refused_when_deleting_fails(directory: FakeDirectory, entra: InMemoryStore) -> None:
    add_member(entra, OWNER_EMAIL, "owner")
    directory.fail = True
    res = client.get("/api/me", headers=entra_principal("stranger@example.com"))
    assert (res.status_code, res.json()["detail"]["reason"]) == (403, "not_invited")


def test_uninvited_google_account_has_nothing_to_delete(directory: FakeDirectory, entra: InMemoryStore) -> None:
    add_member(entra, OWNER_EMAIL, "owner")
    assert client.get("/api/me", headers=principal("stranger@example.com")).status_code == 403
    assert directory.deleted == []


def test_invited_email_account_is_kept(directory: FakeDirectory, entra: InMemoryStore) -> None:
    invite_and_sign_in(entra)
    assert directory.deleted == []


def test_erasing_yourself_deletes_your_email_account_first(directory: FakeDirectory, entra: InMemoryStore) -> None:
    _, member = invite_and_sign_in(entra)
    assert client.delete("/api/me", headers=member).status_code == 204
    assert directory.deleted == ["oid-1"]
    assert entra.get("aad:oid-1") is None


def test_erasure_keeps_everything_when_the_email_account_cannot_be_deleted(
    directory: FakeDirectory, entra: InMemoryStore
) -> None:
    """Nothing half-deleted: the member can simply try again."""
    owner, member = invite_and_sign_in(entra)
    directory.fail = True
    res = client.delete("/api/me", headers=member)
    assert (res.status_code, res.json()["detail"]["reason"]) == (502, "sign_in_account_not_deleted")
    assert entra.get("aad:oid-1") is not None
    res = client.delete("/api/members/aad:oid-1", headers=owner)
    assert res.status_code == 502
    assert entra.get("aad:oid-1") is not None


def test_admin_removal_deletes_the_email_account(directory: FakeDirectory, entra: InMemoryStore) -> None:
    owner, _ = invite_and_sign_in(entra)
    assert client.delete("/api/members/aad:oid-1", headers=owner).status_code == 204
    assert directory.deleted == ["oid-1"]
    assert entra.get("aad:oid-1") is None


def test_removing_a_google_member_calls_nothing(directory: FakeDirectory, entra: InMemoryStore) -> None:
    owner = add_member(entra, OWNER_EMAIL, "owner")
    add_member(entra, "g@example.com", "member")
    assert client.delete("/api/members/google:sub-g@example.com", headers=owner).status_code == 204
    assert directory.deleted == []


@pytest.mark.parametrize(
    "member_id, oid",
    [("aad:abc", "abc"), ("google:abc", None), ("invite-123", None), ("aad:", None), ("dev:x@y", None)],
)
def test_only_email_accounts_have_an_entra_object_id(member_id: str, oid) -> None:
    assert entra_object_id(member_id) == oid


class _Credential:
    def get_token(self, *scopes):
        class T:
            token = "t"

        return T()


@pytest.mark.parametrize("code, ok", [(204, True), (404, True), (403, False), (500, False)])
def test_graph_delete_treats_already_gone_as_done(monkeypatch: pytest.MonkeyPatch, code: int, ok: bool) -> None:
    import io
    import urllib.error

    def fake_urlopen(req, timeout):
        assert (req.get_method(), req.full_url) == ("DELETE", "https://graph.microsoft.com/v1.0/users/oid-1")
        if code == 204:
            return io.BytesIO(b"")
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(entra_module.urllib.request, "urlopen", fake_urlopen)
    graph = GraphDirectory.__new__(GraphDirectory)
    graph.credential = _Credential()
    if ok:
        graph.delete_user("oid-1")
    else:
        with pytest.raises(EntraDeleteFailed):
            graph.delete_user("oid-1")


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
