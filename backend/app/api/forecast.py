import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.forecast import AffordIn, AffordOut, ForecastDayOut, GoalAffordabilityOut
from app.services import forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])

_MAX_MONTHS = 60


def _day_out(day: forecast.ForecastDay) -> ForecastDayOut:
    return ForecastDayOut(
        on=day.on, projected_balance=day.projected_balance, contributions=day.contributions
    )


@router.get("", response_model=list[ForecastDayOut])
def get_forecast(
    months: int = 6, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[ForecastDayOut]:
    if not 1 <= months <= _MAX_MONTHS:
        raise HTTPException(
            status_code=422, detail=f"months must be between 1 and {_MAX_MONTHS}"
        )
    return [_day_out(d) for d in forecast.project(db, hid, months)]


@router.post("/afford", response_model=AffordOut)
def afford(
    body: AffordIn, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> AffordOut:
    result = forecast.can_i_afford(db, hid, body.amount, body.on_date, body.months)
    return AffordOut(
        baseline=[_day_out(d) for d in result.baseline],
        with_amount=[_day_out(d) for d in result.with_amount],
        stays_non_negative=result.stays_non_negative,
        minimum_balance=result.minimum_balance,
        goal_impact=[
            GoalAffordabilityOut(
                goal_id=g.goal_id, goal_name=g.goal_name,
                baseline_date=g.baseline_date, with_amount_date=g.with_amount_date,
            )
            for g in result.goal_impact
        ],
    )
