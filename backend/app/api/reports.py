import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.report import SpendingBucketOut
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
