import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.transaction import Transaction
from app.schemas.transaction import TxnCreate, TxnOut, TxnUpdate
from app.services import transactions

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TxnOut)
def create_txn(
    body: TxnCreate, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> Transaction:
    try:
        return transactions.create(db, hid, body)
    except transactions.AccountNotInHousehold:
        raise HTTPException(status_code=404, detail="Account not found")


@router.get("", response_model=list[TxnOut])
def list_txns(
    account_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    search: str | None = None,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[Transaction]:
    return transactions.list_for(
        db, hid, account_id=account_id, since=since, until=until, search=search
    )


@router.patch("/{txn_id}", response_model=TxnOut)
def update_txn(
    txn_id: uuid.UUID,
    body: TxnUpdate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> Transaction:
    txn = transactions.update(db, hid, txn_id, body)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.delete("/{txn_id}")
def delete_txn(
    txn_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not transactions.delete(db, hid, txn_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"status": "ok"}
