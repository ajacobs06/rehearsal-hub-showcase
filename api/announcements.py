"""Announcements: admins post news for everyone or for some groups; members read them newest first.

Visibility works like rehearsals: no groups = everyone, otherwise only members of those groups
(and admins) can list or open it, and anyone else gets 404.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import current_member, now, require_role
from groups import can_see, check_groups
from models import Announcement, AnnouncementCreate, AnnouncementUpdate, AnnouncementView, Member
from songs import is_admin
from store import DocStore, get_announcement_store, get_group_store

router = APIRouter(prefix="/api/announcements")

LIST_LIMIT = 100


def view(a: Announcement) -> AnnouncementView:
    return AnnouncementView(**a.model_dump(exclude={"authorId"}))


def load(store: DocStore, announcement_id: str, me: Member) -> Announcement:
    doc = store.get(announcement_id)
    if doc is None or not can_see(doc.get("groups", []), me):
        raise HTTPException(404)
    return Announcement(**doc)


@router.get("")
def list_announcements(
    scope: Literal["mine", "all"] = "mine",
    limit: int = Query(LIST_LIMIT, ge=1, le=LIST_LIMIT),
    me: Member = Depends(current_member),
    store: DocStore = Depends(get_announcement_store),
) -> list[AnnouncementView]:
    """Newest first. `mine` (everyone, including admins): for everyone or your groups. `all`
    (admins): every announcement, for the admin page."""
    if scope == "all" and not is_admin(me):
        raise HTTPException(403, detail={"reason": "forbidden"})
    chosen = [
        Announcement(**d)
        for d in store.list_all()
        if scope == "all" or not d.get("groups") or set(d["groups"]) & set(me.groups)
    ]
    chosen.sort(key=lambda a: a.createdAt, reverse=True)
    return [view(a) for a in chosen[:limit]]


@router.get("/{announcement_id}")
def get_announcement(
    announcement_id: str,
    me: Member = Depends(current_member),
    store: DocStore = Depends(get_announcement_store),
) -> AnnouncementView:
    return view(load(store, announcement_id, me))


@router.post("", status_code=201)
def create_announcement(
    body: AnnouncementCreate,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_announcement_store),
    groups: DocStore = Depends(get_group_store),
) -> AnnouncementView:
    check_groups(groups, body.groups)
    a = Announcement(
        id=uuid.uuid4().hex, authorId=admin.id, authorName=admin.name, createdAt=now(), **body.model_dump()
    )
    store.upsert(a.model_dump())
    return view(a)


@router.patch("/{announcement_id}")
def update_announcement(
    announcement_id: str,
    body: AnnouncementUpdate,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_announcement_store),
    groups: DocStore = Depends(get_group_store),
) -> AnnouncementView:
    load(store, announcement_id, admin)
    changes = body.model_dump(exclude_unset=True)
    if "groups" in changes:
        check_groups(groups, changes["groups"])
    doc = store.patch(announcement_id, {(k,): v for k, v in {**changes, "updatedAt": now()}.items()})
    if doc is None:
        raise HTTPException(404)
    return view(Announcement(**doc))


@router.delete("/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: str,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_announcement_store),
) -> None:
    load(store, announcement_id, admin)
    store.delete(announcement_id)


def forget_author(store: DocStore, member_id: str) -> None:
    """Erasure: an erased member's posts stay, signed "Committee" instead of their name."""
    for d in store.find("authorId", member_id):
        store.patch(d["id"], remove_fields=[("authorId",), ("authorName",)])
