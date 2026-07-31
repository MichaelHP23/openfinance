import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.category_rule import MatchType, RuleSource


class CategoryCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str = Field(min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None


class CategoryUpdate(BaseModel):
    model_config = {"str_strip_whitespace": True}
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    is_system: bool
    model_config = {"from_attributes": True}


class RuleCreate(BaseModel):
    match_type: MatchType = MatchType.merchant_contains
    pattern: str
    category_id: uuid.UUID
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    account_id: uuid.UUID | None = None
    priority: int = 100


class RuleUpdate(BaseModel):
    match_type: MatchType | None = None
    pattern: str | None = None
    category_id: uuid.UUID | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    account_id: uuid.UUID | None = None
    priority: int | None = None


class RuleOut(BaseModel):
    id: uuid.UUID
    match_type: MatchType
    pattern: str
    category_id: uuid.UUID
    min_amount: Decimal | None
    max_amount: Decimal | None
    account_id: uuid.UUID | None
    priority: int
    source: RuleSource
    model_config = {"from_attributes": True}


class ReorderIn(BaseModel):
    """Rule ids in the order they should be tried. Priority is rewritten to match."""

    rule_ids: list[uuid.UUID]


class BackfillIn(BaseModel):
    only_uncategorized: bool = True


class UncategorizedOut(BaseModel):
    merchant: str
    count: int
    total: Decimal


class SuggestionOut(BaseModel):
    merchant: str
    category_id: uuid.UUID
    category_name: str


class SuggestResponse(BaseModel):
    suggestions: list[SuggestionOut]
    model: str
