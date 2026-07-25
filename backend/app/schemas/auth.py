import uuid

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
