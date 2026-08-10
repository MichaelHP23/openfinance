from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_owner
from app.core.db import get_db
from app.models.user import User
from app.schemas.audit import AuditEventOut
from app.services import audit

router = APIRouter(prefix="/audit-log", tags=["audit"], dependencies=[Depends(require_owner)])


@router.get("", response_model=list[AuditEventOut])
def list_audit_log(
    since: datetime | None = None,
    action: str | None = None,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> list[AuditEventOut]:
    return [
        AuditEventOut.model_validate(e) for e in audit.list_for(db, owner.household_id, since=since, action=action)
    ]
