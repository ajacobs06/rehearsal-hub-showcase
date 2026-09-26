from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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
    role: Role = "member"
    status: Status
    createdAt: str


class Request(BaseModel):
    """Base for request bodies: unknown fields (e.g. id, status) are rejected, strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InviteRequest(Request):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    part: Part | None = None
    role: Role = "member"


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
    role: Role | None = None

    @field_validator("name", "role")
    @classmethod
    def not_null(cls, v: str | None) -> str:
        # Omit a field to leave it unchanged; an explicit null is an error (part may be null).
        if v is None:
            raise ValueError("cannot be null")
        return v


class InviteResponse(BaseModel):
    member: Member
    emailed: bool


# ---------- Songs ----------

SongStatus = Literal["learning", "performing", "retired"]
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
    files: dict[FileKind, SongFile] = {}
    createdAt: str


class SongCreate(Request):
    title: str = Field(min_length=1, max_length=120)
    arranger: str | None = Field(default=None, max_length=120)
    key: str | None = Field(default=None, max_length=20)
    status: SongStatus = "learning"


class SongUpdate(Request):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    arranger: str | None = Field(default=None, max_length=120)
    key: str | None = Field(default=None, max_length=20)
    status: SongStatus | None = None

    @field_validator("title", "status")
    @classmethod
    def not_null(cls, v: str | None) -> str:
        if v is None:
            raise ValueError("cannot be null")
        return v


class UploadTicket(BaseModel):
    url: str
    contentType: str
    maxBytes: int
    expiresAt: str


class FileLink(BaseModel):
    url: str
    expiresAt: str
