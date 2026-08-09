import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.estate import ChecklistItemOut, ChecklistOut
from app.services import estate

router = APIRouter(prefix="/estate", tags=["estate"])


@router.get("/checklist", response_model=ChecklistOut)
def get_checklist(hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)) -> ChecklistOut:
    result = estate.checklist(db, hid)
    return ChecklistOut(
        items=[ChecklistItemOut(label=i.label, satisfied=i.satisfied, detail=i.detail) for i in result.items],
        gaps=result.gaps,
    )
