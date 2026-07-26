import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountOut
from app.services import accounts

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut)
def create_account(
    body: AccountCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> Account:
    return accounts.create(db, hid, body)


@router.get("", response_model=list[AccountOut])
def list_accounts(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[Account]:
    return accounts.list_for(db, hid)


@router.delete("/{account_id}")
def delete_account(
    account_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not accounts.delete(db, hid, account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}
