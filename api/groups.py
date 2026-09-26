"""Member groups: fixed ones defined here, groups added by admins (e.g. quartets) stored in the
`groups` container.

Groups decide who sees which rehearsals (songs are visible to everyone). Being in the committee
group is what makes someone an admin; owners stay owners regardless.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from auth import current_member, require_role
from models import Group, GroupCreate, GroupMembers, GroupUpdate, Member, Role
from store import DocStore, get_group_store, get_rehearsal_store, get_store

COMMITTEE = "committee"
FIXED: dict[str, str] = {"auditioned": "Auditioned chorus", "open": "Open chorus", COMMITTEE: "Committee"}

router = APIRouter(prefix="/api/groups")


def derived_role(role: Role, groups: list[str]) -> Role:
    if role == "owner":
        return "owner"
    return "admin" if COMMITTEE in groups else "member"


def group_ids(groups: DocStore) -> set[str]:
    return set(FIXED) | {d["id"] for d in groups.list_all()}


def check_groups(groups: DocStore, ids: list[str]) -> None:
    unknown = [g for g in ids if g not in group_ids(groups)]
    if unknown:
        raise HTTPException(400, detail={"reason": "unknown_group", "groups": unknown})


def can_see(item_groups: list[str], member: Member) -> bool:
    """Items with no groups are for everyone; admins see everything."""
    return not item_groups or member.role in ("admin", "owner") or bool(set(item_groups) & set(member.groups))


def require_owner_for_committee(actor: Member, before: list[str], after: list[str]) -> None:
    # Committee membership grants admin, so only owners may change it.
    if (COMMITTEE in before) != (COMMITTEE in after) and actor.role != "owner":
        raise HTTPException(403, detail={"reason": "owner_only_committee"})


def load_custom(groups: DocStore, group_id: str) -> dict:
    if group_id in FIXED:
        raise HTTPException(400, detail={"reason": "fixed_group"})
    doc = groups.get(group_id)
    if doc is None:
        raise HTTPException(404)
    return doc


@router.get("")
def list_groups(
    _: Member = Depends(current_member),
    groups: DocStore = Depends(get_group_store),
    members: DocStore = Depends(get_store),
) -> list[Group]:
    counts: dict[str, int] = {}
    for m in members.list_all():
        for g in m.get("groups", []):
            counts[g] = counts.get(g, 0) + 1
    fixed = [Group(id=gid, name=name, kind="fixed", memberCount=counts.get(gid, 0)) for gid, name in FIXED.items()]
    custom = sorted(
        (Group(id=d["id"], name=d["name"], kind="custom", memberCount=counts.get(d["id"], 0)) for d in groups.list_all()),
        key=lambda g: g.name.lower(),
    )
    return fixed + custom


@router.post("", status_code=201)
def create_group(
    body: GroupCreate,
    _: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
) -> Group:
    group = Group(id=f"q-{uuid.uuid4().hex[:12]}", name=body.name, kind="custom")
    groups.upsert({"id": group.id, "name": group.name})
    return group


@router.patch("/{group_id}")
def rename_group(
    group_id: str,
    body: GroupUpdate,
    _: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
) -> Group:
    doc = load_custom(groups, group_id)
    groups.upsert({**doc, "name": body.name})
    return Group(id=group_id, name=body.name, kind="custom")


@router.delete("/{group_id}", status_code=204)
def delete_group(
    group_id: str,
    _: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
    members: DocStore = Depends(get_store),
    rehearsals: DocStore = Depends(get_rehearsal_store),
) -> None:
    load_custom(groups, group_id)
    for m in members.list_all():
        if group_id in m.get("groups", []):
            members.patch(m["id"], {("groups",): [g for g in m["groups"] if g != group_id]})
    for r in rehearsals.list_all():
        if group_id in r.get("groups", []):
            rehearsals.patch(r["id"], {("groups",): [g for g in r["groups"] if g != group_id]})
    groups.delete(group_id)


@router.put("/{group_id}/members")
def set_group_members(
    group_id: str,
    body: GroupMembers,
    actor: Member = Depends(require_role("admin")),
    groups: DocStore = Depends(get_group_store),
    members: DocStore = Depends(get_store),
) -> Group:
    """Replace who is in one group (e.g. pick a quartet's four singers)."""
    check_groups(groups, [group_id])
    wanted = set(dict.fromkeys(body.memberIds))
    all_members = {d["id"]: d for d in members.list_all()}
    unknown = sorted(wanted - set(all_members))
    if unknown:
        raise HTTPException(400, detail={"reason": "unknown_member", "memberIds": unknown})
    changes = []
    for mid, doc in all_members.items():
        before = doc.get("groups", [])
        inside = group_id in before
        if (mid in wanted) == inside:
            continue
        after = [*before, group_id] if mid in wanted else [g for g in before if g != group_id]
        require_owner_for_committee(actor, before, after)
        changes.append((mid, doc, after))
    for mid, doc, after in changes:
        members.patch(mid, {("groups",): after, ("role",): derived_role(doc["role"], after)})
    name = FIXED.get(group_id) or groups.get(group_id)["name"]
    kind = "fixed" if group_id in FIXED else "custom"
    return Group(id=group_id, name=name, kind=kind, memberCount=len(wanted))
