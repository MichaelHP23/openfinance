import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.connection import ProviderConnection
from app.providers.simplefin import SimpleFinError
from app.schemas.connection import ConnectionOut, SimpleFinLink, SyncOut
from app.services import connections

router = APIRouter(prefix="/connections", tags=["connections"])


def _out(conn: ProviderConnection) -> ConnectionOut:
    return ConnectionOut(
        id=conn.id,
        provider=conn.provider.value,
        status=conn.status.value,
        last_synced_at=conn.last_synced_at,
    )


@router.get("", response_model=list[ConnectionOut])
def list_connections(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[ConnectionOut]:
    return [_out(c) for c in connections.list_for(db, hid)]


@router.post("/simplefin", response_model=SyncOut)
def link_simplefin(
    body: SimpleFinLink,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> SyncOut:
    """Claim a setup token and immediately pull everything it exposes."""
    try:
        conn = connections.link_simplefin(db, hid, body.setup_token)
        result = connections.sync(db, hid, conn)
    except SimpleFinError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return SyncOut(**result.__dict__)


@router.post("/{connection_id}/sync", response_model=SyncOut)
def sync_connection(
    connection_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> SyncOut:
    conn = connections.get(db, hid, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        result = connections.sync(db, hid, conn)
    except SimpleFinError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return SyncOut(**result.__dict__)


@router.delete("/{connection_id}")
def delete_connection(
    connection_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not connections.delete(db, hid, connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"status": "ok"}
