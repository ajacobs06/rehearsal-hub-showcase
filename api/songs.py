import re
import uuid

from fastapi import APIRouter, Depends, HTTPException

from auth import current_member, now, require_role
from models import (
    ROLE_RANK,
    FileKind,
    FileLink,
    Member,
    Song,
    SongCreate,
    SongFile,
    SongUpdate,
    UploadTicket,
)
from store import DocStore, get_song_store
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
) -> list[Song]:
    songs = [Song(**d) for d in store.list_all()]
    if not is_admin(member):
        songs = [s for s in songs if s.status != "retired"]
    return sorted(songs, key=lambda s: (STATUS_ORDER[s.status], s.title.lower()))


@router.get("/{song_id}")
def get_song(
    song_id: str,
    member: Member = Depends(current_member),
    store: DocStore = Depends(get_song_store),
) -> Song:
    return load_song(store, song_id, member)


@router.post("", status_code=201)
def create_song(
    body: SongCreate,
    _: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
) -> Song:
    song = Song(id=uuid.uuid4().hex, createdAt=now(), **body.model_dump())
    store.upsert(song.model_dump())
    return song


@router.patch("/{song_id}")
def update_song(
    song_id: str,
    body: SongUpdate,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
) -> Song:
    song = load_song(store, song_id, admin)
    return save(store, song, body.model_dump(exclude_unset=True))


@router.delete("/{song_id}", status_code=204)
def delete_song(
    song_id: str,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
    tracks: TrackStore = Depends(get_track_store),
) -> None:
    load_song(store, song_id, admin)
    tracks.delete_prefix(f"{song_id}/")
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
    tracks: TrackStore = Depends(get_track_store),
) -> Song:
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
    return save(store, song, {"files": files})


@router.delete("/{song_id}/files/{kind}")
def delete_file(
    song_id: str,
    kind: FileKind,
    admin: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_song_store),
    tracks: TrackStore = Depends(get_track_store),
) -> Song:
    song = load_song(store, song_id, admin)
    tracks.delete(blob_path(song_id, kind))
    return save(store, song, {"files": {k: v for k, v in song.files.items() if k != kind}})


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

