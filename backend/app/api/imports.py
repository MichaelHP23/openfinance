import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import require_household
from app.core.db import get_db
from app.services import csv_import

router = APIRouter(prefix="/accounts", tags=["imports"])


@router.post("/{account_id}/import")
async def import_transactions(
    account_id: uuid.UUID, file: UploadFile,
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db),
):
    raw = (await file.read()).decode()
    try:
        res = csv_import.import_csv(db, hid, account_id, raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"imported": res.imported, "skipped": res.skipped}
