import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from auth import current_member, easy_auth_enabled, now, require_role
from mailer import Mailer, get_mailer
from models import ROLE_RANK, InviteRequest, InviteResponse, MeUpdate, Member, MemberUpdate, Role
from store import MemberStore, get_store

# The React build is copied here at deploy time (see .github/workflows/deploy.yml).
STATIC_DIR = (Path(__file__).parent / "static").resolve()

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


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
    store: MemberStore = Depends(get_store),
) -> Member:
    updated = apply_update(member, body.model_dump(exclude_unset=True))
    store.upsert(updated.model_dump())
    return updated


# ---------- Member management (admin) ----------


def apply_update(member: Member, changes: dict) -> Member:
    """Merge changes and re-validate the whole record before it is stored."""
    return Member.model_validate({**member.model_dump(), **changes})


def can_manage(actor: Member, role: Role) -> bool:
    """Owners manage everyone; otherwise you can only manage roles below your own."""
    return actor.role == "owner" or ROLE_RANK[actor.role] > ROLE_RANK[role]


@app.get("/api/members")
def list_members(
    _: Member = Depends(require_role("admin")),
    store: MemberStore = Depends(get_store),
) -> list[Member]:
    members = [Member(**d) for d in store.list_all()]
    return sorted(members, key=lambda m: (m.status != "active", m.name.lower()))


@app.post("/api/members", status_code=201)
def invite_member(
    body: InviteRequest,
    actor: Member = Depends(require_role("admin")),
    store: MemberStore = Depends(get_store),
    mailer: Mailer = Depends(get_mailer),
) -> InviteResponse:
    if not can_manage(actor, body.role):
        raise HTTPException(403, detail={"reason": "forbidden"})
    email = body.email.strip().lower()
    if store.find_by_email(email):
        raise HTTPException(409, detail={"reason": "already_exists"})
    invite = Member(
        id=f"invite-{uuid.uuid4().hex}",
        email=email,
        name=body.name.strip(),
        part=body.part,
        role=body.role,
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
    store: MemberStore = Depends(get_store),
) -> Member:
    doc = store.get(member_id)
    if doc is None:
        raise HTTPException(404)
    target = Member(**doc)
    if not can_manage(actor, target.role):
        raise HTTPException(403, detail={"reason": "forbidden"})
    if body.role is not None and body.role != target.role:
        if target.id == actor.id:
            raise HTTPException(400, detail={"reason": "cannot_change_own_role"})
        if not can_manage(actor, body.role):
            raise HTTPException(403, detail={"reason": "forbidden"})
    updated = apply_update(target, body.model_dump(exclude_unset=True))
    store.upsert(updated.model_dump())
    return updated


@app.delete("/api/members/{member_id}", status_code=204)
def delete_member(
    member_id: str,
    actor: Member = Depends(require_role("admin")),
    store: MemberStore = Depends(get_store),
) -> None:
    doc = store.get(member_id)
    if doc is None:
        raise HTTPException(404)
    if member_id == actor.id:
        raise HTTPException(400, detail={"reason": "cannot_delete_self"})
    if not can_manage(actor, Member(**doc).role):
        raise HTTPException(403, detail={"reason": "forbidden"})
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
