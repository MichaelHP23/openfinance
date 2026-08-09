import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.report import MonthFlowOut, SpendingBucketOut, YearInReviewOut
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/spending", response_model=list[SpendingBucketOut])
def get_spending(
    start: date,
    end: date,
    group_by: Literal["category", "merchant", "month"] = "category",
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[SpendingBucketOut]:
    try:
        buckets = reports.spending(db, hid, start, end, group_by)
    except reports.BadGroupBy:
        raise HTTPException(status_code=422, detail="group_by must be category, merchant, or month")
    return [SpendingBucketOut(key=b.key, key_id=b.key_id, total=b.total, count=b.count) for b in buckets]


@router.get("/income-vs-expense", response_model=list[MonthFlowOut])
def get_income_vs_expense(
    months: int = 12, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[MonthFlowOut]:
    return [
        MonthFlowOut(month=m.month, income=m.income, expense=m.expense, net=m.net)
        for m in reports.income_vs_expense(db, hid, months)
    ]


@router.get("/year-in-review", response_model=YearInReviewOut)
def get_year_in_review(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> YearInReviewOut:
    r = reports.year_in_review(db, hid, year)
    return YearInReviewOut(
        year=r.year, total_in=r.total_in, total_out=r.total_out, savings_rate=r.savings_rate,
        biggest_category=r.biggest_category, biggest_category_amount=r.biggest_category_amount,
        biggest_transaction_merchant=r.biggest_transaction_merchant,
        biggest_transaction_amount=r.biggest_transaction_amount,
        new_subscriptions=r.new_subscriptions, cancelled_subscriptions=r.cancelled_subscriptions,
        net_worth_delta=r.net_worth_delta,
    )
