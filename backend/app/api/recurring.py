import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.recurring import RecurringSeries, SeriesStatus
from app.schemas.recurring import (
    ChargeOut,
    DetectionResultOut,
    SeriesDetailOut,
    SeriesOut,
    SeriesUpdate,
    SummaryOut,
    UpcomingOut,
)
from app.services import recurring

router = APIRouter(prefix="/recurring", tags=["recurring"])


@router.get("", response_model=list[SeriesOut])
def list_series(
    status: str = "active",
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[RecurringSeries]:
    filter_status: SeriesStatus | None
    if status == "all":
        filter_status = None
    else:
        try:
            filter_status = SeriesStatus(status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status: {status}")
    return recurring.list_for(db, hid, status=filter_status)


@router.get("/summary", response_model=SummaryOut)
def get_summary(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> SummaryOut:
    s = recurring.summary(db, hid)
    return SummaryOut(
        monthly_committed=s.monthly_committed,
        monthly_incoming=s.monthly_incoming,
        active_count=s.active_count,
        upcoming=[UpcomingOut(**u) for u in s.upcoming],  # type: ignore[arg-type]
        price_increases=s.price_increases,
        last_detected_at=s.last_detected_at,
    )


@router.post("/refresh", response_model=DetectionResultOut)
def refresh(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> DetectionResultOut:
    result = recurring.detect(db, hid)
    return DetectionResultOut(
        detected=result.detected,
        updated=result.updated,
        ended=result.ended,
        removed=result.removed,
    )


@router.get("/{series_id}", response_model=SeriesDetailOut)
def get_series(
    series_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> SeriesDetailOut:
    series = recurring.get(db, hid, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Recurring series not found")
    txns = recurring.charges(db, hid, series)
    data = SeriesOut.model_validate(series).model_dump()
    return SeriesDetailOut(**data, charges=[ChargeOut.model_validate(t) for t in txns])


@router.patch("/{series_id}", response_model=SeriesOut)
def update_series(
    series_id: uuid.UUID,
    body: SeriesUpdate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> RecurringSeries:
    series = recurring.update(db, hid, series_id, body)
    if series is None:
        raise HTTPException(status_code=404, detail="Recurring series not found")
    return series
