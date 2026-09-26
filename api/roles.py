"""Role derivation, shared by auth (every request) and the groups and member endpoints.

Role is never trusted as stored: owner stays owner; otherwise a member is an admin exactly when
they are in a group with admin access *right now*. The stored `role` is kept in step for display,
but authorisation always recomputes it, so a lost update can't leave someone with stale access.
"""

from models import Role
from store import DocStore

# Created once, the first time groups are used, so existing memberships keep working. After
# that they are ordinary groups: renamed, deleted or given admin access like any other.
DEFAULT_GROUPS = [
    {"id": "auditioned", "name": "Auditioned chorus", "admin": False},
    {"id": "open", "name": "Open chorus", "admin": False},
    {"id": "committee", "name": "Committee", "admin": True},
]
META_ID = "_meta"


def stored_groups(groups: DocStore) -> list[dict]:
    if groups.get(META_ID) is None:
        existing = {d["id"] for d in groups.list_all()}
        for g in DEFAULT_GROUPS:
            if g["id"] not in existing:
                groups.upsert(g)
        groups.upsert({"id": META_ID, "seeded": True})
    return [d for d in groups.list_all() if not d["id"].startswith("_")]


def group_ids(groups: DocStore) -> set[str]:
    return {d["id"] for d in stored_groups(groups)}


def admin_group_ids(groups: DocStore) -> set[str]:
    return {d["id"] for d in stored_groups(groups) if d.get("admin")}


def member_groups(doc: dict) -> list[str]:
    """A member doc's groups. Accounts from before groups existed have none stored: admins and
    owners count as Committee (which is what makes someone an admin from then on)."""
    if "groups" in doc:
        return doc["groups"]
    return ["committee"] if doc.get("role") in ("admin", "owner") else []


def current_role(doc: dict, admin_ids: set[str]) -> Role:
    """The role to authorise with, from the member's groups and today's admin groups."""
    return derived_role(doc["role"], member_groups(doc), admin_ids)


def derived_role(role: Role, member_groups: list[str], admin_ids: set[str]) -> Role:
    if role == "owner":
        return "owner"
    return "admin" if set(member_groups) & admin_ids else "member"
