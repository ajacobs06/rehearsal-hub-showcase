from fastapi import APIRouter, Depends

from auth import require_role
from models import Member, Song, Tracker, TrackerEntry, TrackerMember, TrackerSong
from songs import STATUS_ORDER
from store import DocStore, get_progress_store, get_song_store, get_store

router = APIRouter(prefix="/api/tracker")


@router.get("")
def get_tracker(
    _: Member = Depends(require_role("admin")),
    members: DocStore = Depends(get_store),
    songs: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> Tracker:
    """Every active member x non-retired song, with the part they sing for it and their state."""
    active = sorted(
        (Member(**d) for d in members.list_all() if d["status"] == "active"), key=lambda m: m.name.lower()
    )
    current = sorted(
        (Song(**d) for d in songs.list_all() if d["status"] != "retired"),
        key=lambda s: (STATUS_ORDER[s.status], s.title.lower()),
    )
    docs = {(d["memberId"], d["songId"]): d for d in progress.list_all()}
    entries = []
    for song in current:
        for m in active:
            doc = docs.get((m.id, song.id), {})
            entries.append(
                TrackerEntry(
                    songId=song.id,
                    memberId=m.id,
                    part=doc.get("part") or m.part,
                    state=doc.get("state") or "not_started",
                )
            )
    return Tracker(
        songs=[TrackerSong(id=s.id, title=s.title, status=s.status) for s in current],
        members=[TrackerMember(id=m.id, name=m.name, part=m.part) for m in active],
        entries=entries,
    )
