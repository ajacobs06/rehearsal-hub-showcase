import re
import uuid

from fastapi import APIRouter, Depends, HTTPException

from auth import current_member, now, require_role
from models import (
    ROLE_RANK,
    FileKind,
    FileLink,
    Member,
    MyPartRequest,
    MyStateRequest,
    Song,
    SongCreate,
    SongFile,
    SongUpdate,
    SongView,
    UploadTicket,
)
from store import DocStore, get_progress_store, get_song_store
from tracks import TrackStore, get_track_store

router = APIRouter(prefix="/api/songs")

MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024
STATUS_ORDER = {"learning": 0, "performing": 1, "retired": 2}
KIND_LABEL = {"tenor": "Tenor", "lead": "Lead", "bari": "Bari", "bass": "Bass", "full": "Full mix", "score": "Score"}


def is_admin(member: Member) -> bool:
    return ROLE_RANK[member.role] >= ROLE_RANK["admin"]


def blob_path(song_id: str, kind: str) -> str:
    return f"{song_id}/{'score.pdf' if kind == 'score' else f'{kind}.mp3'}"


def content_type(kind: str) -> str:
    return "application/pdf" if kind == "score" else "audio/mpeg"


def looks_valid(kind: str, head: bytes) -> bool:
    """Check the file's first bytes: a PDF header, or an MP3 (ID3 tag or MPEG frame sync)."""
    if kind == "score":
        return head.startswith(b"%PDF-")
    return head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)


def load_song(store: DocStore, song_id: str, member: Member) -> Song:
    doc = store.get(song_id)
    # Retired songs are hidden from members; answer 404 rather than revealing they exist.
    if doc is None or (doc["status"] == "retired" and not is_admin(member)):
        raise HTTPException(404)
    return Song(**doc)


def progress_id(member_id: str, song_id: str) -> str:
    return f"{member_id}:{song_id}"


def view_from(song: Song, member: Member, doc: dict | None) -> SongView:
    """The song plus this member's part for it (per-song choice, else usual part) and learned state."""
    doc = doc or {}
    override = doc.get("part")
    return SongView(
        **song.model_dump(),
        myPart=override or member.part,
        partOverride=override is not None,
        myState=doc.get("state") or "not_started",
    )


def view(song: Song, member: Member, progress: DocStore) -> SongView:
    return view_from(song, member, progress.get(progress_id(member.id, song.id), partition=song.id))


def load_progress(progress: DocStore, member: Member, song_id: str) -> dict:
    pid = progress_id(member.id, song_id)
    return progress.get(pid, partition=song_id) or {"id": pid, "memberId": member.id, "songId": song_id}


def save_progress(progress: DocStore, doc: dict) -> None:
    """Store the doc, or delete it when it holds nothing (no per-song part, not started)."""
    doc = {**doc, "updatedAt": now()}
    if not doc.get("part") and (doc.get("state") or "not_started") == "not_started":
        progress.delete(doc["id"], partition=doc["songId"])
    else:
        progress.upsert(doc)


def save(store: DocStore, song: Song, changes: dict) -> Song:
    """Merge changes and re-validate the whole record before it is stored."""
    updated = Song.model_validate({**song.model_dump(), **changes})
    store.upsert(updated.model_dump())
    return updated


# ---------- Songs ----------


@router.get("")
def list_songs(
    member: Member = Depends(current_member),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> list[SongView]:
    songs = [Song(**d) for d in store.list_all()]
    if not is_admin(member):
        songs = [s for s in songs if s.status != "retired"]
    mine = {d["songId"]: d for d in progress.find("memberId", member.id)}
    views = [view_from(s, member, mine.get(s.id)) for s in songs]
    return sorted(views, key=lambda s: (STATUS_ORDER[s.status], s.title.lower()))


@router.get("/{song_id}")
def get_song(
    song_id: str,
    member: Member = Depends(current_member),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> SongView:
    return view(load_song(store, song_id, member), member, progress)


@router.put("/{song_id}/my-part")
def set_my_part(
    song_id: str,
    body: MyPartRequest,
    member: Member = Depends(current_member),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> SongView:
    """Learn a different part for one song. null (or your usual part) removes the per-song choice."""
    song = load_song(store, song_id, member)
    part = body.part if body.part != member.part else None
    save_progress(progress, {**load_progress(progress, member, song_id), "part": part})
    return view(song, member, progress)


@router.put("/{song_id}/my-state")
def set_my_state(
    song_id: str,
    body: MyStateRequest,
    member: Member = Depends(current_member),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> SongView:
    """How far the member has got with this song: not_started, learning, learned or ready."""
    song = load_song(store, song_id, member)
    save_progress(progress, {**load_progress(progress, member, song_id), "state": body.state})
    return view(song, member, progress)


@router.post("", status_code=201)
def create_song(
    body: SongCreate,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
) -> SongView:
    song = Song(id=uuid.uuid4().hex, createdAt=now(), **body.model_dump())
    store.upsert(song.model_dump())
    return SongView(**song.model_dump(), myPart=admin.part)


@router.patch("/{song_id}")
def update_song(
    song_id: str,
    body: SongUpdate,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
) -> SongView:
    song = load_song(store, song_id, admin)
    return view(save(store, song, body.model_dump(exclude_unset=True)), admin, progress)


@router.delete("/{song_id}", status_code=204)
def delete_song(
    song_id: str,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
    tracks: TrackStore = Depends(get_track_store),
) -> None:
    load_song(store, song_id, admin)
    tracks.delete_prefix(f"{song_id}/")
    for doc in progress.find("songId", song_id):
        progress.delete(doc["id"], partition=song_id)
    store.delete(song_id)


# ---------- Files ----------


@router.post("/{song_id}/files/{kind}/upload")
def start_upload(
    song_id: str,
    kind: FileKind,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
    tracks: TrackStore = Depends(get_track_store),
) -> UploadTicket:
    load_song(store, song_id, admin)
    url, expiry = tracks.upload_url(blob_path(song_id, kind), content_type(kind))
    return UploadTicket(
        url=url,
        contentType=content_type(kind),
        maxBytes=MAX_PDF_BYTES if kind == "score" else MAX_AUDIO_BYTES,
        expiresAt=expiry.isoformat(timespec="seconds"),
    )


@router.post("/{song_id}/files/{kind}/complete")
def complete_upload(
    song_id: str,
    kind: FileKind,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
    tracks: TrackStore = Depends(get_track_store),
) -> SongView:
    """Called after the browser uploads. Only files that pass these checks become visible."""
    song = load_song(store, song_id, admin)
    path = blob_path(song_id, kind)
    info = tracks.info(path)
    if info is None:
        raise HTTPException(400, detail={"reason": "upload_missing"})
    limit = MAX_PDF_BYTES if kind == "score" else MAX_AUDIO_BYTES
    reason = None
    if info.size == 0:
        reason = "empty"
    elif info.size > limit:
        reason = "too_large"
    elif not looks_valid(kind, tracks.first_bytes(path, 8)):
        reason = "wrong_type"
    if reason:
        tracks.delete(path)
        # The previous good file (if any) was overwritten by this upload, so forget it too.
        files = {k: v for k, v in song.files.items() if k != kind}
        save(store, song, {"files": files})
        raise HTTPException(400, detail={"reason": reason})
    files = {**song.files, kind: SongFile(size=info.size, uploadedAt=now())}
    return view(save(store, song, {"files": files}), admin, progress)


@router.delete("/{song_id}/files/{kind}")
def delete_file(
    song_id: str,
    kind: FileKind,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
    progress: DocStore = Depends(get_progress_store),
    tracks: TrackStore = Depends(get_track_store),
) -> SongView:
    song = load_song(store, song_id, admin)
    tracks.delete(blob_path(song_id, kind))
    updated = save(store, song, {"files": {k: v for k, v in song.files.items() if k != kind}})
    return view(updated, admin, progress)


@router.get("/{song_id}/files/{kind}")
def file_link(
    song_id: str,
    kind: FileKind,
    download: bool = False,
    member: Member = Depends(current_member),
    store: DocStore = Depends(get_song_store),
    tracks: TrackStore = Depends(get_track_store),
) -> FileLink:
    song = load_song(store, song_id, member)
    if kind not in song.files:
        raise HTTPException(404)
    name = None
    if download:
        safe_title = re.sub(r"[^A-Za-z0-9 ._-]", "", song.title).strip() or "track"
        ext = "pdf" if kind == "score" else "mp3"
        name = f"{safe_title} - {KIND_LABEL[kind]}.{ext}"
    url, expiry = tracks.read_url(blob_path(song_id, kind), content_type(kind), name)
    return FileLink(url=url, expiresAt=expiry.isoformat(timespec="seconds"))

