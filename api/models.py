from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Part = Literal["tenor", "lead", "bari", "bass"]
Role = Literal["member", "admin", "owner"]
Status = Literal["invited", "active"]

ROLE_RANK: dict[str, int] = {"member": 0, "admin": 1, "owner": 2}


class Member(BaseModel):
    # Active members: "<idp>:<user id>" from the sign-in provider. Invites: "invite-<uuid>".
    id: str
    email: str
    name: str
    part: Part | None = None
    role: Role = "member"
    status: Status
    createdAt: str


class InviteRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    part: Part | None = None
    role: Role = "member"


class MemberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    part: Part | None = None
    role: Role | None = None


class InviteResponse(BaseModel):
    member: Member
    emailed: bool
