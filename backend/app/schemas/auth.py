import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class Credentials(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    household_id: uuid.UUID
    # Lets the client hide login/logout affordances that mean nothing without auth.
    local_mode: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime | None
    is_current: bool


class TwoFAEnrollOut(BaseModel):
    secret: str
    provisioning_uri: str


class TwoFACode(BaseModel):
    code: str


class PreauthCode(BaseModel):
    preauth_token: str
    code: str


class LoginResult(BaseModel):
    status: str  # "ok" | "totp_required"
    user: UserOut | None = None
    preauth_token: str | None = None


class InviteCreateOut(BaseModel):
    id: uuid.UUID
    token: str
    expires_at: datetime


class InviteOut(BaseModel):
    id: uuid.UUID
    role: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    model_config = {"from_attributes": True}


class JoinIn(BaseModel):
    token: str
    email: EmailStr
    password: str
