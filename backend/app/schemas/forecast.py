import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ForecastDayOut(BaseModel):
    on: date
    projected_balance: Decimal
    contributions: list[str]


class AffordIn(BaseModel):
    amount: Decimal = Field(gt=0)
    on_date: date
    months: int = Field(default=6, ge=1, le=60)


class GoalAffordabilityOut(BaseModel):
    goal_id: uuid.UUID
    goal_name: str
    baseline_date: date | None
    with_amount_date: date | None


class AffordOut(BaseModel):
    baseline: list[ForecastDayOut]
    with_amount: list[ForecastDayOut]
    stays_non_negative: bool
    minimum_balance: Decimal
    goal_impact: list[GoalAffordabilityOut]
