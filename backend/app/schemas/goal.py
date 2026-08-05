import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.goal import GoalKind, GoalStatus


class GoalCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(min_length=1, max_length=200)
    kind: GoalKind
    target_amount: Decimal = Field(gt=0)
    target_date: date | None = None
    monthly_funding: Decimal | None = Field(default=None, ge=0)
    account_ids: list[uuid.UUID] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: GoalKind | None = None
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_date: date | None = None
    monthly_funding: Decimal | None = Field(default=None, ge=0)
    status: GoalStatus | None = None
    account_ids: list[uuid.UUID] | None = None


class GoalOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: GoalKind
    target_amount: Decimal
    target_date: date | None
    monthly_funding: Decimal | None
    status: GoalStatus
    account_ids: list[uuid.UUID]
    progress: Decimal
    projected_date: date | None
