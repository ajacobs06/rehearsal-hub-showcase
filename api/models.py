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
