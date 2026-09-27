import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from account import router as account_router
from announcements import forget_author
from announcements import router as announcements_router
from auth import current_member, dev_auth_enabled, easy_auth_enabled, now, require_role
from entra import EntraDirectory, delete_sign_in_accounts, get_directory
from feedback import router as feedback_router
from mailer import Mailer, get_mailer
from models import ROLE_RANK, InviteRequest, InviteResponse, MeUpdate, Member, MemberUpdate, Role
from rehearsals import router as rehearsals_router
from security import SecurityMiddleware, invite_limiter
from songs import router as songs_router
from groups import check_groups, require_owner_for_admin_groups
from groups import router as groups_router
from roles import admin_group_ids, current_role, derived_role, member_groups
from store import (
    DocStore,
    get_announcement_store,
    get_feedback_store,
    get_group_store,
    get_progress_store,
    get_rehearsal_store,
    get_store,
)
from tracker import router as tracker_router

# The React build is copied here at deploy time (see .github/workflows/deploy.yml).
STATIC_DIR = (Path(__file__).parent / "static").resolve()

# Server-side error monitoring (Application Insights), only where it's configured: never in tests
# or local dev. No browser tracking; App Insights masks client IPs.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    configure_azure_monitor()
    # FastAPI was imported before monitoring started, so instrument this app explicitly;
    # otherwise incoming requests aren't recorded.
    FastAPIInstrumentor.instrument_app(app)
if dev_auth_enabled():
    logging.getLogger(__name__).warning(
        "DEV AUTH ON: every request is signed in as %s. Never set ALLOW_DEV_AUTH outside local dev.",
        os.environ["DEV_USER_EMAIL"],
    )

# Body cap, early 401 for anonymous writes and rate limits, before FastAPI reads anything.
app.add_middleware(SecurityMiddleware)
app.include_router(songs_router)
app.include_router(tracker_router)
app.include_router(rehearsals_router)
app.include_router(groups_router)
app.include_router(feedback_router)
app.include_router(account_router)
app.include_router(announcements_router)


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    # easyAuth: whether the API trusts sign-in headers. Must be true in production.
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "easyAuth": easy_auth_enabled(),
    }


# ---------- Current member ----------


@app.get("/api/me")
def get_me(member: Member = Depends(current_member)) -> Member:
    return member


@app.patch("/api/me")
def update_me(
    body: MeUpdate,
    member: Member = Depends(current_member),
    store: DocStore = Depends(get_store),
) -> Member:
    changes = body.model_dump(exclude_unset=True)
    updated = apply_update(member, changes)
    patch_member(store, updated, changes.keys())
    return updated


# ---------- Member management (admin) ----------


def apply_update(member: Member, changes: dict) -> Member:
    """Merge changes and re-validate the whole record before it is stored."""
    return Member.model_validate({**member.model_dump(), **changes})


def patch_member(store: DocStore, member: Member, fields) -> None:
    """Write only the fields that changed, so a concurrent edit to other fields (e.g. a group's
    admin access changing everyone's role) isn't overwritten by a stale copy of the whole doc."""
    doc = member.model_dump()
    if fields:
        store.patch(member.id, {(f,): doc[f] for f in fields})


def can_manage(actor: Member, role: Role) -> bool:
    """Owners manage everyone; otherwise you can only manage roles below your own."""
    return actor.role == "owner" or ROLE_RANK[actor.role] > ROLE_RANK[role]


@app.get("/api/members")
def list_members(
    _: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_store),
    groups: DocStore = Depends(get_group_store),
) -> list[Member]:
    admin_ids = admin_group_ids(groups)
    members = [
        Member(**{**d, "groups": member_groups(d), "role": current_role(d, admin_ids)}) for d in store.list_all()
    ]
    return sorted(members, key=lambda m: (m.status != "active", m.name.lower()))


@app.post("/api/members", status_code=201)
def invite_member(
    body: InviteRequest,
    actor: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_store),
    groups: DocStore = Depends(get_group_store),
    mailer: Mailer = Depends(get_mailer),
) -> InviteResponse:
    if not invite_limiter.allow(actor.id):
        raise HTTPException(429, detail={"reason": "too_many_invites"})
    check_groups(groups, body.groups)
    admin_ids = admin_group_ids(groups)
    require_owner_for_admin_groups(actor, [], body.groups, admin_ids)
    email = body.email.strip().lower()
    if store.find("email", email):
        raise HTTPException(409, detail={"reason": "already_exists"})
    invite = Member(
        id=f"invite-{uuid.uuid4().hex}",
        email=email,
        name=body.name.strip(),
        part=body.part,
        role=derived_role("member", body.groups, admin_ids),
        groups=body.groups,
        status="invited",
        createdAt=now(),
    )
    store.upsert(invite.model_dump())
    emailed = mailer.send_invite(email, invite.name, actor.name)
    return InviteResponse(member=invite, emailed=emailed)


@app.patch("/api/members/{member_id}")
def update_member(
    member_id: str,
    body: MemberUpdate,
    actor: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_store),
    groups: DocStore = Depends(get_group_store),
) -> Member:
    """Name/part follow the usual manage rules. Any admin may change groups for anyone, except
    groups with admin access and owner status, which are for owners only."""
    doc = store.get(member_id)
    if doc is None:
        raise HTTPException(404)
    admin_ids = admin_group_ids(groups)
    target = Member(**{**doc, "groups": member_groups(doc), "role": current_role(doc, admin_ids)})
    changes = body.model_dump(exclude_unset=True)
    if {"name", "part"} & changes.keys() and not can_manage(actor, target.role):
        raise HTTPException(403, detail={"reason": "forbidden"})
    new_groups = changes.get("groups", target.groups)
    if "groups" in changes:
        check_groups(groups, new_groups)
        require_owner_for_admin_groups(actor, target.groups, new_groups, admin_ids)
    role = target.role
    if "owner" in changes:
        if actor.role != "owner":
            raise HTTPException(403, detail={"reason": "forbidden"})
        if target.id == actor.id and changes["owner"] != (target.role == "owner"):
            raise HTTPException(400, detail={"reason": "cannot_change_own_role"})
        role = "owner" if changes.pop("owner") else "member"
    changes["role"] = derived_role(role, new_groups, admin_ids)
    updated = apply_update(target, changes)
    # A doc from before groups existed gets its (defaulted) groups stored with this edit.
    patch_member(store, updated, changes.keys() | ({"groups"} if "groups" not in doc else set()))
    return updated


@app.delete("/api/members/{member_id}", status_code=204)
def delete_member(
    member_id: str,
    actor: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_store),
    progress: DocStore = Depends(get_progress_store),
    rehearsals: DocStore = Depends(get_rehearsal_store),
    feedback: DocStore = Depends(get_feedback_store),
    groups: DocStore = Depends(get_group_store),
    directory: EntraDirectory = Depends(get_directory),
    announcements: DocStore = Depends(get_announcement_store),
) -> None:
    doc = store.get(member_id)
    if doc is None:
        raise HTTPException(404)
    if member_id == actor.id:
        raise HTTPException(400, detail={"reason": "cannot_delete_self"})
    if not can_manage(actor, current_role(doc, admin_group_ids(groups))):
        raise HTTPException(403, detail={"reason": "forbidden"})
    delete_sign_in_accounts([member_id, *doc.get("logins", [])], directory)
    for p in progress.find("memberId", member_id):
        progress.delete(p["id"], partition=p["songId"])
    for r in rehearsals.list_all():
        if member_id in r.get("rsvps", {}):
            rehearsals.patch(r["id"], remove_fields=[("rsvps", member_id)])
    for f in feedback.find("memberId", member_id):
        feedback.delete(f["id"])
    forget_author(announcements, member_id)
    store.delete(member_id)


# ---------- Front end ----------

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (STATIC_DIR / path).resolve()
        if path and file.is_file() and file.is_relative_to(STATIC_DIR):
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")
