import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class BudgetItemIn(BaseModel):
    category_id: uuid.UUID
    amount: Decimal
    rollover: bool = False


class BudgetsUpsertIn(BaseModel):
    items: list[BudgetItemIn]


class BudgetOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    month: date
    amount: Decimal
    rollover: bool
    model_config = {"from_attributes": True}


class CategoryBudgetStatusOut(BaseModel):
    category_id: uuid.UUID
    category_name: str
    budgeted: Decimal
    carry_in: Decimal
    effective_budget: Decimal
    actual: Decimal
    remaining: Decimal
    pace: float | None
    rollover: bool


class BudgetSuggestionOut(BaseModel):
    category_id: uuid.UUID
    category_name: str
    amount: Decimal


class CopyIn(BaseModel):
    """`from` is a Python keyword, so the wire field is aliased onto `from_month`. The
    request body is `{"from": "2026-06"}`, matching the spec's own example verbatim."""

    from_month: str = Field(alias="from")
