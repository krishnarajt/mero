from datetime import datetime

from pydantic import BaseModel, Field


# ---- requests ----


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class JoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


# ---- responses ----


class UserOut(BaseModel):
    id: int
    username: str


class TokenResponse(BaseModel):
    token: str
    user: UserOut


class OkResponse(BaseModel):
    ok: bool = True
    # Set when deleting a workspace you don't own, which leaves it instead.
    left: bool | None = None


class BoardSummary(BaseModel):
    id: str
    name: str
    created_at: datetime | None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    is_owner: bool
    invite_code: str
    members: list[str]
    boards: list[BoardSummary]


class WorkspaceCreated(BaseModel):
    id: str
    name: str
    invite_code: str


class WorkspaceRef(BaseModel):
    id: str
    name: str


class BoardCreated(BaseModel):
    id: str
    name: str
    workspace_id: str


class BoardOut(BaseModel):
    id: str
    name: str
    workspace: WorkspaceRef
