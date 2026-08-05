import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.goal import Goal
from app.schemas.goal import GoalCreate, GoalOut, GoalUpdate
from app.services import forecast, goals

router = APIRouter(prefix="/goals", tags=["goals"])


def _out(
    db: Session,
    household_id: uuid.UUID,
    row: Goal,
    overview: dict[uuid.UUID, forecast.GoalOverview],
) -> GoalOut:
    o = overview.get(row.id)
    return GoalOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        target_amount=row.target_amount,
        target_date=row.target_date,
        monthly_funding=row.monthly_funding,
        status=row.status,
        account_ids=goals.linked_account_ids(db, household_id, row.id),
        progress=o.progress if o else Decimal(0),
        projected_date=o.projected_date if o else None,
    )


@router.get("", response_model=list[GoalOut])
def list_goals(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[GoalOut]:
    overview = {o.goal_id: o for o in forecast.goals_overview(db, hid)}
    return [_out(db, hid, row, overview) for row in goals.list_for(db, hid)]


@router.post("", response_model=GoalOut)
def create_goal(
    body: GoalCreate, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> GoalOut:
    try:
        row = goals.create(
            db, hid, name=body.name, kind=body.kind, target_amount=body.target_amount,
            target_date=body.target_date, monthly_funding=body.monthly_funding,
            account_ids=body.account_ids,
        )
    except goals.UnknownAccount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    overview = {o.goal_id: o for o in forecast.goals_overview(db, hid)}
    return _out(db, hid, row, overview)


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(
    goal_id: uuid.UUID, body: GoalUpdate,
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db),
) -> GoalOut:
    try:
        row = goals.update(db, hid, goal_id, body)
    except goals.UnknownAccount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    overview = {o.goal_id: o for o in forecast.goals_overview(db, hid)}
    return _out(db, hid, row, overview)


@router.delete("/{goal_id}")
def delete_goal(
    goal_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not goals.delete(db, hid, goal_id):
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"status": "ok"}
