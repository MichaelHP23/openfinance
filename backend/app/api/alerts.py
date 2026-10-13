import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.alerts import AlertOut, DismissIn
from app.services import alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[alerts.Alert]:
    return alerts.list_for(db, hid)


# The key rides in the body, not the path: it contains colons.
@router.post("/dismiss", status_code=204)
def dismiss_alert(
    body: DismissIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> Response:
    alerts.dismiss(db, hid, body.key)
    return Response(status_code=204)
