import re
from typing import Literal

from datetime import timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Part = Literal["tenor", "lead", "bari", "bass"]
Role = Literal["member", "admin", "owner"]
Status = Literal["invited", "active"]

ROLE_RANK: dict[str, int] = {"member": 0, "admin": 1, "owner": 2}


class Member(BaseModel):
    # Active members: "<idp>:<user id>" from the sign-in provider. Invites: "invite-<uuid>".
    id: str
    email: str
    name: str = Field(min_length=1, max_length=100)
    part: Part | None = None
    # Derived: owner stays owner; otherwise admin exactly when in a group with admin access.
    role: Role = "member"
    status: Status
    groups: list[str] = []
    createdAt: str


class Request(BaseModel):
    """Base for request bodies: unknown fields (e.g. id, status) are rejected, strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _dedupe_ids(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


class InviteRequest(Request):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    part: Part | None = None
    groups: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("groups")
    @classmethod
    def dedupe_groups(cls, v: list[str]) -> list[str]:
        return _dedupe_ids(v)


class MeUpdate(Request):
    """What members may change about themselves. Role is deliberately absent."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    part: Part | None = None

    @field_validator("name")
    @classmethod
    def name_not_null(cls, v: str | None) -> str:
        if v is None:
            raise ValueError("name cannot be null")
        return v


class MemberUpdate(Request):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    part: Part | None = None
    groups: list[str] | None = Field(default=None, max_length=50)
    owner: bool | None = None  # owners only

    @field_validator("name", "groups", "owner")
    @classmethod
    def not_null(cls, v):
        # Omit a field to leave it unchanged; an explicit null is an error (part may be null).
        if v is None:
            raise ValueError("cannot be null")
        return _dedupe_ids(v) if isinstance(v, list) else v


class Group(BaseModel):
    id: str
    name: str
    admin: bool = False  # members of this group are admins
    memberCount: int = 0


class GroupCreate(Request):
    name: str = Field(min_length=1, max_length=60)
    admin: bool = False


class GroupUpdate(Request):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    admin: bool | None = None

    @field_validator("name", "admin")
    @classmethod
    def not_null(cls, v):
        if v is None:
            raise ValueError("cannot be null")
        return v


class GroupMembers(Request):
    memberIds: list[str] = Field(max_length=500)


class InviteResponse(BaseModel):
    member: Member
    emailed: bool


# ---------- Songs ----------

SongStatus = Literal["learning", "performing", "retired"]
Difficulty = Literal["easy", "medium", "hard"]
SongKind = Literal["song", "tag"]  # a full song, or a barbershop tag (short ending phrase)
MAX_TAGS = 10
TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 &'-]{0,29}$")


def normalise_tags(tags: list[str]) -> list[str]:
    """Lowercase, trim and collapse spaces, drop duplicates; reject anything odd."""
    out: list[str] = []
    for raw in tags:
        tag = " ".join(raw.split()).lower()
        if not TAG_PATTERN.match(tag):
            raise ValueError(f"tag {raw!r} must be 1-30 letters, numbers, spaces or & ' -")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    return out
FileKind = Literal["tenor", "lead", "bari", "bass", "full", "score"]
AUDIO_KINDS: tuple[str, ...] = ("tenor", "lead", "bari", "bass", "full")


class SongFile(BaseModel):
    size: int
    uploadedAt: str


class Song(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=120)
    arranger: str | None = Field(default=None, max_length=120)
    key: str | None = Field(default=None, max_length=20)
    status: SongStatus = "learning"
    kind: SongKind = "song"
    difficulty: Difficulty | None = None
    tags: list[str] = []
    files: dict[FileKind, SongFile] = {}
    createdAt: str


class SongCreate(Request):
    title: str = Field(min_length=1, max_length=120)
    arranger: str | None = Field(default=None, max_length=120)
    key: str | None = Field(default=None, max_length=20)
    status: SongStatus = "learning"
    kind: SongKind = "song"
    difficulty: Difficulty | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: list[str]) -> list[str]:
        return normalise_tags(v)


class SongUpdate(Request):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    arranger: str | None = Field(default=None, max_length=120)
    key: str | None = Field(default=None, max_length=20)
    status: SongStatus | None = None
    kind: SongKind | None = None
    difficulty: Difficulty | None = None  # null clears it
    tags: list[str] | None = Field(default=None, max_length=50)

    @field_validator("title", "status", "kind", "tags")
    @classmethod
    def not_null(cls, v):
        if v is None:
            raise ValueError("cannot be null")
        return normalise_tags(v) if isinstance(v, list) else v


class UploadTicket(BaseModel):
    url: str
    contentType: str
    maxBytes: int
    expiresAt: str


class FileLink(BaseModel):
    url: str
    expiresAt: str


LearnState = Literal["not_started", "learning", "learned", "ready"]


class SongView(Song):
    """A song as seen by one member: the part they are learning for it and how far they've got."""

    myPart: Part | None = None
    partOverride: bool = False
    myState: LearnState = "not_started"


class MyPartRequest(Request):
    # Required key; null means "go back to my usual part".
    part: Part | None


class MyStateRequest(Request):
    state: LearnState


class TrackerSong(BaseModel):
    id: str
    title: str
    status: SongStatus


class TrackerMember(BaseModel):
    id: str
    name: str
    part: Part | None


class TrackerEntry(BaseModel):
    songId: str
    memberId: str
    part: Part | None  # the part this member sings for this song
    state: LearnState


class Tracker(BaseModel):
    songs: list[TrackerSong]
    members: list[TrackerMember]
    entries: list[TrackerEntry]  # one per active member x non-retired song


# ---------- Rehearsals ----------

RsvpResponse = Literal["yes", "maybe", "no"]
MAX_REHEARSAL_LENGTH = timedelta(hours=12)


def _check_times(start, end) -> None:
    if end is not None and start is not None:
        if end <= start:
            raise ValueError("end must be after start")
        if end - start > MAX_REHEARSAL_LENGTH:
            raise ValueError("a rehearsal can't be longer than 12 hours")


def _dedupe(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


class Rsvp(BaseModel):
    response: RsvpResponse
    updatedAt: str


class Rehearsal(BaseModel):
    id: str
    start: AwareDatetime
    end: AwareDatetime | None = None
    venue: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    songIds: list[str] = Field(default_factory=list, max_length=30)
    groups: list[str] = []  # empty = everyone
    rsvps: dict[str, Rsvp] = {}
    createdAt: str

    @model_validator(mode="after")
    def times(self) -> "Rehearsal":
        _check_times(self.start, self.end)
        return self


class RehearsalCreate(Request):
    start: AwareDatetime
    end: AwareDatetime | None = None
    venue: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    songIds: list[str] = Field(default_factory=list, max_length=30)
    groups: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("songIds", "groups")
    @classmethod
    def dedupe_ids(cls, v: list[str]) -> list[str]:
        return _dedupe(v)

    @model_validator(mode="after")
    def times(self) -> "RehearsalCreate":
        _check_times(self.start, self.end)
        return self


class RehearsalUpdate(Request):
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    venue: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    songIds: list[str] | None = Field(default=None, max_length=30)
    groups: list[str] | None = Field(default=None, max_length=50)

    @field_validator("start", "venue", "songIds", "groups")
    @classmethod
    def not_null(cls, v):
        # Omit a field to leave it unchanged; end and notes may be cleared with null.
        if v is None:
            raise ValueError("cannot be null")
        return _dedupe(v) if isinstance(v, list) else v


class RsvpRequest(Request):
    # Required key; null withdraws the RSVP.
    response: RsvpResponse | None


class RehearsalSong(BaseModel):
    id: str
    title: str
    status: SongStatus
    myPart: Part | None
    myState: LearnState
    hasMyTrack: bool


class RsvpCounts(BaseModel):
    yes: int = 0
    maybe: int = 0
    no: int = 0
    noReply: int = 0


class PartCount(BaseModel):
    yes: int = 0
    maybe: int = 0


class SongParts(BaseModel):
    """For one song on the plan: how many in each part are coming (by the part they sing on it)."""

    songId: str
    title: str
    parts: dict[str, PartCount]  # tenor/lead/bari/bass/none


class Attendee(BaseModel):
    memberId: str
    name: str
    part: Part | None
    response: RsvpResponse | None


class RehearsalView(BaseModel):
    id: str
    start: AwareDatetime
    end: AwareDatetime | None
    venue: str
    notes: str | None
    songs: list[RehearsalSong]
    groups: list[str]
    myRsvp: RsvpResponse | None
    rsvpOpen: bool
    counts: RsvpCounts
    # Admins only:
    attendees: list[Attendee] | None = None
    songParts: list[SongParts] | None = None


# ---------- Feedback ----------

FeedbackStatus = Literal["new", "done"]


class Feedback(BaseModel):
    id: str
    memberId: str
    name: str
    email: str
    message: str
    page: str | None = None
    status: FeedbackStatus = "new"
    createdAt: str


class FeedbackCreate(Request):
    message: str = Field(min_length=1, max_length=2000)
    page: str | None = Field(default=None, max_length=200)


class FeedbackUpdate(Request):
    status: FeedbackStatus
