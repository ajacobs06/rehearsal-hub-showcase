import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request

from entra import EntraDeleteFailed, EntraDirectory, entra_object_id, get_directory
from models import ROLE_RANK, Member, Role
from roles import admin_group_ids, current_role, member_groups
from store import DocStore, get_group_store, get_store, on_app_service

CLAIM_ID = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
CLAIM_EMAIL = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
CLAIM_OID = "http://schemas.microsoft.com/identity/claims/objectidentifier"
CLAIM_TID = "http://schemas.microsoft.com/identity/claims/tenantid"

# Sign-in providers whose email claims we trust. Invites and owner bootstrap match on email, so a
# provider that lets people set an unverified email (e.g. GitHub) must never be added here.
# "aad" is our own Entra External ID tenant (email and password), trusted only from ENTRA_TENANT_ID.
ALLOWED_PROVIDERS = {"google", "aad"}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Principal:
    member_id: str  # "<idp>:<user id>", stable per sign-in account
    email: str
    name: str


def parse_client_principal(header: str) -> Principal | None:
    """Parse App Service Easy Auth's X-MS-CLIENT-PRINCIPAL (base64 JSON with a claims list)."""
    try:
        data = json.loads(base64.b64decode(header))
    except (ValueError, TypeError):
        return None
    claims: dict[str, str] = {}
    for c in data.get("claims", []):
        claims.setdefault(c.get("typ", ""), c.get("val", ""))
    email = (claims.get(CLAIM_EMAIL) or claims.get("email") or "").strip().lower()
    idp = data.get("auth_typ")
    if idp == "google":
        user_id = claims.get(CLAIM_ID) or claims.get("sub")
        # Must be present and true: a missing claim is not a verified email.
        if claims.get("email_verified", "").lower() != "true":
            return None
    elif idp == "aad":
        user_id = claims.get(CLAIM_OID) or claims.get("oid")
        if not entra_account_trusted(claims.get(CLAIM_TID) or claims.get("tid")):
            return None
    else:
        return None
    if not user_id or not email:
        return None
    return Principal(member_id=f"{idp}:{user_id}", email=email, name=claims.get("name") or email)


def email_sign_in_enabled() -> bool:
    """Set (with the Entra provider) by infra/main.bicep once the external tenant exists."""
    return bool(os.environ.get("ENTRA_TENANT_ID", "").strip())


def entra_account_trusted(tenant_id: str | None) -> bool:
    """Entra sends no email_verified claim. Our external tenant only lets people sign up with an
    email and password after proving the address with a one-time code, so its emails are verified.
    Any other tenant's (e.g. a work account where an admin can type in any email) are not."""
    expected = os.environ.get("ENTRA_TENANT_ID", "").strip().lower()
    return bool(expected) and (tenant_id or "").strip().lower() == expected


def easy_auth_enabled() -> bool:
    """App Service sets this when built-in auth is on."""
    return os.environ.get("WEBSITE_AUTH_ENABLED", "").lower() == "true"


def dev_auth_enabled() -> bool:
    """Local development only: DEV_USER_EMAIL signs everyone in as that user. Needs an explicit
    ALLOW_DEV_AUTH=1 and is refused on anything that looks like App Service."""
    return (
        bool(os.environ.get("DEV_USER_EMAIL"))
        and os.environ.get("ALLOW_DEV_AUTH") == "1"
        and not on_app_service()
        and not any(k.startswith("WEBSITE_") for k in os.environ)
    )


def get_principal(request: Request) -> Principal | None:
    # Easy Auth strips client-supplied X-MS-* headers only when it is enabled, so the header is
    # trusted only then. Anywhere else it could be forged.
    if easy_auth_enabled():
        header = request.headers.get("x-ms-client-principal")
        return parse_client_principal(header) if header else None
    if dev_auth_enabled():
        email = os.environ["DEV_USER_EMAIL"].strip().lower()
        return Principal(member_id=f"dev:{email}", email=email, name=email.split("@")[0])
    return None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_member(
    principal: Principal | None = Depends(get_principal),
    store: DocStore = Depends(get_store),
    groups: DocStore = Depends(get_group_store),
    directory: EntraDirectory = Depends(get_directory),
) -> Member:
    if principal is None:
        # Tells the welcome page whether to offer email and password sign-in yet.
        raise HTTPException(401, detail={"reason": "not_signed_in", "emailSignIn": email_sign_in_enabled()})

    existing = store.get(principal.member_id)
    if existing:
        if "groups" not in existing:
            # Accounts from before groups existed get their groups stored (see member_groups).
            existing = {**existing, "groups": member_groups(existing)}
            store.patch(existing["id"], {("groups",): existing["groups"]})
        # Authorise on the role as it is now, not as last stored (see roles.py).
        role = current_role(existing, admin_group_ids(groups))
        if role != existing["role"]:
            existing = {**existing, "role": role}
            store.patch(existing["id"], {("role",): role})
        return Member(**existing)

    # First sign-in: claim an invite for this email, or bootstrap the first owner.
    invite = next((d for d in store.find("email", principal.email) if d["status"] == "invited"), None)
    if invite:
        doc = {**invite, "id": principal.member_id, "status": "active"}
        store.upsert(doc)
        store.delete(invite["id"])
        return Member(**doc)

    # Only for an empty database (a fresh deploy or local dev): once any owner exists this does
    # nothing, so a second account with the same email can't make itself owner.
    owner_email = os.environ.get("BOOTSTRAP_OWNER_EMAIL", "").strip().lower()
    if owner_email and principal.email == owner_email and not store.find("role", "owner"):
        doc = {
            "id": principal.member_id,
            "email": principal.email,
            "name": principal.name,
            "part": None,
            "role": "owner",
            "groups": ["committee"],
            "status": "active",
            "createdAt": now(),
        }
        store.upsert(doc)
        return Member(**doc)

    # An uninvited email-and-password sign-up leaves nothing of theirs in our Entra tenant. If
    # they're invited later, they sign up again.
    oid = entra_object_id(principal.member_id)
    if oid:
        try:
            directory.delete_user(oid)
        except EntraDeleteFailed as e:
            log.warning("Could not delete uninvited Entra account %s: %s", oid, e)
    raise HTTPException(403, detail={"reason": "not_invited", "email": principal.email})


def require_role(min_role: Role) -> Callable[..., Member]:
    """Endpoint dependency: `member: Member = Depends(require_role("admin"))`."""

    def check(member: Member = Depends(current_member)) -> Member:
        if ROLE_RANK[member.role] < ROLE_RANK[min_role]:
            raise HTTPException(403, detail={"reason": "forbidden"})
        return member

    return check
