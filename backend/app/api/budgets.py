import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.budget import (
    BudgetOut,
    BudgetSuggestionOut,
    BudgetsUpsertIn,
    CategoryBudgetStatusOut,
    CopyIn,
)
from app.services import budgets

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _parse_month(value: str) -> date:
    try:
        return budgets.parse_month(value)
    except budgets.BadMonth as exc:
        raise HTTPException(
            status_code=422, detail=f"'{value}' is not a YYYY-MM month"
        ) from exc


@router.get("/{month}", response_model=list[CategoryBudgetStatusOut])
def get_status(
    month: str,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[CategoryBudgetStatusOut]:
    parsed = _parse_month(month)
    return [
        CategoryBudgetStatusOut(
            category_id=row.category_id,
            category_name=row.category_name,
            budgeted=row.budgeted,
            carry_in=row.carry_in,
            effective_budget=row.effective_budget,
            actual=row.actual,
            remaining=row.remaining,
            pace=row.pace,
            rollover=row.rollover,
        )
        for row in budgets.status(db, hid, parsed)
    ]


@router.put("/{month}", response_model=list[BudgetOut])
def upsert_budgets(
    month: str,
    body: BudgetsUpsertIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[BudgetOut]:
    parsed = _parse_month(month)
    items = [
        budgets.BudgetItem(category_id=i.category_id, amount=i.amount, rollover=i.rollover)
        for i in body.items
    ]
    try:
        return budgets.upsert(db, hid, parsed, items)  # type: ignore[return-value]
    except budgets.UnknownCategory as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{month}/suggest", response_model=list[BudgetSuggestionOut])
def suggest_budgets(
    month: str,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[BudgetSuggestionOut]:
    parsed = _parse_month(month)
    return [
        BudgetSuggestionOut(
            category_id=s.category_id, category_name=s.category_name, amount=s.amount
        )
        for s in budgets.suggest(db, hid, parsed)
    ]


@router.post("/{month}/copy")
def copy_budgets(
    month: str,
    body: CopyIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    dst = _parse_month(month)
    src = _parse_month(body.from_month)
    return {"copied": budgets.copy_from(db, hid, src, dst)}
