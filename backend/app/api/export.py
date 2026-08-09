import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.services import export

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/all.zip")
def export_all(hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)) -> Response:
    data = export.build_zip(db, hid)
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="openfinance-export.zip"'},
    )
