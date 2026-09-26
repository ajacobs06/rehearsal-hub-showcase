import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from auth import current_member, now, require_role
from models import (
    Attendee,
    Member,
    PartCount,
    Rehearsal,
    RehearsalCreate,
    RehearsalSong,
    RehearsalUpdate,
    RehearsalView,
    RsvpCounts,
    RsvpRequest,
    Song,
    SongParts,
)
from groups import can_see, check_groups
from songs import is_admin
from store import DocStore, get_group_store, get_progress_store, get_rehearsal_store, get_song_store, get_store

router = APIRouter(prefix="/api/rehearsals")

# Without an end time, a rehearsal counts as finished (and RSVPs close) this long after it starts.
DEFAULT_LENGTH = timedelta(hours=3)
PAST_LIMIT = 20


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def finishes(r: Rehearsal) -> datetime:
    return r.end or r.start + DEFAULT_LENGTH


def load(store: DocStore, rehearsal_id: str, me: Member) -> Rehearsal:
    doc = store.get(rehearsal_id)
    # Rehearsals for groups you're not in answer 404 rather than revealing they exist.
    if doc is None or not can_see(doc.get("groups", []), me):
        raise HTTPException(404)
    return Rehearsal(**doc)


def check_songs(songs: DocStore, song_ids: list[str]) -> None:
    missing = [sid for sid in song_ids if songs.get(sid) is None]
    if missing:
        raise HTTPException(400, detail={"reason": "unknown_song", "songIds": missing})


def build_view(
    r: Rehearsal, me: Member, members: DocStore, songs: DocStore, progress: DocStore
) -> RehearsalView:
    admin = is_admin(me)
    plan = [Song(**d) for sid in r.songIds if (d := songs.get(sid))]
    if not admin:
        plan = [s for s in plan if s.status != "retired"]
    mine = {d["songId"]: d for d in progress.find("memberId", me.id)}
    song_views = [
        RehearsalSong(
            id=s.id,
            title=s.title,
            status=s.status,
            myPart=(part := (mine.get(s.id, {}).get("part") or me.part)),
            myState=mine.get(s.id, {}).get("state") or "not_started",
            hasMyTrack=bool(part and part in s.files),
        )
        for s in plan
    ]

    # Only the rehearsal's audience counts (everyone, or the members of its groups).
    active = [
        m
        for m in (Member(**d) for d in members.list_all() if d["status"] == "active")
        if not r.groups or set(r.groups) & set(m.groups)
    ]
    counts = RsvpCounts()
    for m in active:
        rsvp = r.rsvps.get(m.id)
        if rsvp is None:
            counts.noReply += 1
        else:
            setattr(counts, rsvp.response, getattr(counts, rsvp.response) + 1)

    view = RehearsalView(
        id=r.id,
        start=r.start,
        end=r.end,
        venue=r.venue,
        notes=r.notes,
        songs=song_views,
        groups=r.groups,
        myRsvp=r.rsvps[me.id].response if me.id in r.rsvps else None,
        rsvpOpen=utcnow() < finishes(r),
        counts=counts,
    )
    if admin:
        view.attendees = sorted(
            (
                Attendee(
                    memberId=m.id,
                    name=m.name,
                    part=m.part,
                    response=r.rsvps[m.id].response if m.id in r.rsvps else None,
                )
                for m in active
            ),
            key=lambda a: a.name.lower(),
        )
        coming = [m for m in active if m.id in r.rsvps and r.rsvps[m.id].response != "no"]
        view.songParts = []
        for s in plan:
            overrides = {d["memberId"]: d.get("part") for d in progress.find("songId", s.id)}
            parts: dict[str, PartCount] = {}
            for m in coming:
                key = overrides.get(m.id) or m.part or "none"
                count = parts.setdefault(key, PartCount())
                setattr(count, r.rsvps[m.id].response, getattr(count, r.rsvps[m.id].response) + 1)
            view.songParts.append(SongParts(songId=s.id, title=s.title, parts=parts))
    return view


# ---------- Reading ----------


@router.get("")
def list_rehearsals(
    when: Literal["upcoming", "past"] = "upcoming",
    scope: Literal["mine", "all"] = "mine",
    me: Member = Depends(current_member),
    store: DocStore = Depends(get_rehearsal_store),
    members: DocStore = Depends(get_store),
    songs: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> list[RehearsalView]:
    """`mine` (everyone, including admins): rehearsals for everyone or your groups.
    `all` (admins): every rehearsal, for the admin page."""
    if scope == "all" and not is_admin(me):
        raise HTTPException(403, detail={"reason": "forbidden"})
    now_ = utcnow()
    all_ = [
        Rehearsal(**d)
        for d in store.list_all()
        if scope == "all" or not d.get("groups") or set(d["groups"]) & set(me.groups)
    ]
    if when == "upcoming":
        chosen = sorted((r for r in all_ if finishes(r) > now_), key=lambda r: r.start)
    else:
        chosen = sorted((r for r in all_ if finishes(r) <= now_), key=lambda r: r.start, reverse=True)[:PAST_LIMIT]
    return [build_view(r, me, members, songs, progress) for r in chosen]


@router.get("/{rehearsal_id}")
def get_rehearsal(
    rehearsal_id: str,
    me: Member = Depends(current_member),
    store: DocStore = Depends(get_rehearsal_store),
    members: DocStore = Depends(get_store),
    songs: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> RehearsalView:
    return build_view(load(store, rehearsal_id, me), me, members, songs, progress)


# ---------- RSVP ----------


@router.put("/{rehearsal_id}/rsvp")
def rsvp(
    rehearsal_id: str,
    body: RsvpRequest,
    me: Member = Depends(current_member),
    store: DocStore = Depends(get_rehearsal_store),
    members: DocStore = Depends(get_store),
    songs: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> RehearsalView:
    r = load(store, rehearsal_id, me)
    if utcnow() >= finishes(r):
        raise HTTPException(400, detail={"reason": "rsvp_closed"})
    # Patch only this member's entry, so simultaneous RSVPs can't overwrite each other.
    if body.response is None:
        doc = store.patch(rehearsal_id, remove_fields=[("rsvps", me.id)])
    else:
        doc = store.patch(rehearsal_id, {("rsvps", me.id): {"response": body.response, "updatedAt": now()}})
    if doc is None:
        raise HTTPException(404)
    return build_view(Rehearsal(**doc), me, members, songs, progress)


# ---------- Admin ----------


@router.post("", status_code=201)
def create_rehearsal(
    body: RehearsalCreate,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_rehearsal_store),
    members: DocStore = Depends(get_store),
    songs: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
    groups: DocStore = Depends(get_group_store),
) -> RehearsalView:
    check_songs(songs, body.songIds)
    check_groups(groups, body.groups)
    r = Rehearsal(id=uuid.uuid4().hex, createdAt=now(), rsvps={}, **body.model_dump())
    store.upsert(r.model_dump(mode="json"))
    return build_view(r, admin, members, songs, progress)


@router.patch("/{rehearsal_id}")
def update_rehearsal(
    rehearsal_id: str,
    body: RehearsalUpdate,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_rehearsal_store),
    members: DocStore = Depends(get_store),
    songs: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
    groups: DocStore = Depends(get_group_store),
) -> RehearsalView:
    current = load(store, rehearsal_id, admin)
    changes = body.model_dump(exclude_unset=True, mode="json")
    if "songIds" in changes:
        check_songs(songs, changes["songIds"])
    if "groups" in changes:
        check_groups(groups, changes["groups"])
    # Validate the merged record, then patch only the changed fields so RSVPs made meanwhile survive.
    try:
        Rehearsal.model_validate({**current.model_dump(mode="json"), **changes})
    except ValidationError as e:
        raise HTTPException(422, detail=[{"msg": err["msg"]} for err in e.errors()])
    doc = store.patch(rehearsal_id, {(k,): v for k, v in changes.items()})
    if doc is None:
        raise HTTPException(404)
    return build_view(Rehearsal(**doc), admin, members, songs, progress)


@router.delete("/{rehearsal_id}", status_code=204)
def delete_rehearsal(
    rehearsal_id: str,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_rehearsal_store),
) -> None:
    load(store, rehearsal_id, admin)
    store.delete(rehearsal_id)
