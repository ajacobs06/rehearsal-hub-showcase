"""Member groups, all stored in the `groups` container and editable from the admin page.

Groups decide who sees which rehearsals (songs are visible to everyone). A group can give its
members admin access; owners stay owners regardless. Changing anything that grants admin
(the setting, membership of such a group, deleting it) is for owners only.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from auth import current_member, require_role
from models import Group, GroupCreate, GroupMembers, GroupUpdate, Member
from roles import DEFAULT_GROUPS, admin_group_ids, derived_role, group_ids, member_groups, stored_groups
from store import DocStore, get_announcement_store, get_group_store, get_rehearsal_store, get_store

router = APIRouter(prefix="/api/groups")


def check_groups(groups: DocStore, ids: list[str]) -> None:
    known = group_ids(groups)
    unknown = [g for g in ids if g not in known]
    if unknown:
        raise HTTPException(400, detail={"reason": "unknown_group", "groups": unknown})


def can_see(item_groups: list[str], member: Member) -> bool:
    """Items with no groups are for everyone; admins see everything."""
    return not item_groups or member.role in ("admin", "owner") or bool(set(item_groups) & set(member.groups))


def require_owner_for_admin_groups(actor: Member, before: list[str], after: list[str], admin_ids: set[str]) -> None:
    # Joining or leaving a group with admin access changes who is an admin: owners only.
    if set(before) & admin_ids != set(after) & admin_ids and actor.role != "owner":
        raise HTTPException(403, detail={"reason": "owner_only_admin_group"})


def recompute_roles(members: DocStore, admin_ids: set[str]) -> None:
    for m in members.list_all():
        role = derived_role(m["role"], m.get("groups", []), admin_ids)
        if role != m["role"]:
            members.patch(m["id"], {("role",): role})


def load_group(groups: DocStore, group_id: str) -> dict:
    doc = next((d for d in stored_groups(groups) if d["id"] == group_id), None)
    if doc is None:
        raise HTTPException(404)
    return doc


def to_group(doc: dict, count: int = 0) -> Group:
    return Group(id=doc["id"], name=doc["name"], admin=bool(doc.get("admin")), memberCount=count)


@router.get("")
def list_groups(
    me: Member = Depends(current_member),
    groups: DocStore = Depends(get_group_store),
    members: DocStore = Depends(get_store),
) -> list[Group]:
    """Admins get every group with member counts. Members only get their own groups (to name them
    on their account and rehearsals), without counts: which quartets exist is the committee's."""
    docs = stored_groups(groups)
    counts: dict[str, int] = {}
    if me.role == "member":
        docs = [d for d in docs if d["id"] in me.groups]
    else:
        for m in members.list_all():
            for g in member_groups(m):
                counts[g] = counts.get(g, 0) + 1
    # Defaults first in their usual order, then the rest by name.
    order = {g["id"]: i for i, g in enumerate(DEFAULT_GROUPS)}
    docs.sort(key=lambda d: (order.get(d["id"], len(order)), d["name"].lower()))
    return [to_group(d, counts.get(d["id"], 0)) for d in docs]


@router.post("", status_code=201)
def create_group(
    body: GroupCreate,
    actor: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
) -> Group:
    if body.admin and actor.role != "owner":
        raise HTTPException(403, detail={"reason": "owner_only_admin_group"})
    stored_groups(groups)  # make sure the defaults exist before the first new group
    doc = {"id": f"g-{uuid.uuid4().hex[:12]}", "name": body.name, "admin": body.admin}
    groups.upsert(doc)
    return to_group(doc)


@router.patch("/{group_id}")
def update_group(
    group_id: str,
    body: GroupUpdate,
    actor: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
    members: DocStore = Depends(get_store),
) -> Group:
    doc = load_group(groups, group_id)
    changes = body.model_dump(exclude_unset=True)
    if "admin" in changes and changes["admin"] != bool(doc.get("admin")):
        if actor.role != "owner":
            raise HTTPException(403, detail={"reason": "owner_only_admin_group"})
    doc = {**doc, **changes}
    groups.upsert(doc)
    if "admin" in changes:
        recompute_roles(members, admin_group_ids(groups))
    return to_group(doc, sum(1 for m in members.list_all() if group_id in m.get("groups", [])))


@router.delete("/{group_id}", status_code=204)
def delete_group(
    group_id: str,
    actor: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
    members: DocStore = Depends(get_store),
    rehearsals: DocStore = Depends(get_rehearsal_store),
    announcements: DocStore = Depends(get_announcement_store),
) -> None:
    doc = load_group(groups, group_id)
    if doc.get("admin") and actor.role != "owner":
        raise HTTPException(403, detail={"reason": "owner_only_admin_group"})
    groups.delete(group_id)
    for m in members.list_all():
        if group_id in m.get("groups", []):
            members.patch(m["id"], {("groups",): [g for g in m["groups"] if g != group_id]})
    for r in rehearsals.list_all():
        if group_id in r.get("groups", []):
            rehearsals.patch(r["id"], {("groups",): [g for g in r["groups"] if g != group_id]})
    # An announcement loses the group only if it has others. If it was the only audience the id
    # stays: it matches nobody, so the post is for admins only rather than suddenly for everyone
    # (which an empty list would mean).
    for a in announcements.list_all():
        rest = [g for g in a.get("groups", []) if g != group_id]
        if group_id in a.get("groups", []) and rest:
            announcements.patch(a["id"], {("groups",): rest})
    if doc.get("admin"):
        recompute_roles(members, admin_group_ids(groups))


@router.put("/{group_id}/members")
def set_group_members(
    group_id: str,
    body: GroupMembers,
    actor: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
    members: DocStore = Depends(get_store),
) -> Group:
    """Replace who is in one group (e.g. pick a quartet's four singers)."""
    doc = load_group(groups, group_id)
    admin_ids = admin_group_ids(groups)
    wanted = set(dict.fromkeys(body.memberIds))
    all_members = {d["id"]: d for d in members.list_all()}
    unknown = sorted(wanted - set(all_members))
    if unknown:
        raise HTTPException(400, detail={"reason": "unknown_member", "memberIds": unknown})
    changes = []
    for mid, m in all_members.items():
        before = m.get("groups", [])
        if (mid in wanted) == (group_id in before):
            continue
        after = [*before, group_id] if mid in wanted else [g for g in before if g != group_id]
        require_owner_for_admin_groups(actor, before, after, admin_ids)
        changes.append((mid, m, after))
    for mid, m, after in changes:
        members.patch(mid, {("groups",): after, ("role",): derived_role(m["role"], after, admin_ids)})
    return to_group(doc, len(wanted))
