import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.schemas.transaction import TxnCreate, TxnUpdate
from app.services import accounts


class AccountNotInHousehold(Exception):
    pass


def _assert_account(db: Session, household_id: uuid.UUID, account_id: uuid.UUID) -> None:
    if accounts.get(db, household_id, account_id) is None:
        raise AccountNotInHousehold(str(account_id))


def create(db: Session, household_id: uuid.UUID, data: TxnCreate) -> Transaction:
    _assert_account(db, household_id, data.account_id)
    txn = Transaction(
        household_id=household_id,
        account_id=data.account_id,
        posted_at=data.posted_at,
        amount=data.amount,
        currency=data.currency,
        merchant_raw=data.merchant_raw,
        category_id=data.category_id,
        notes=data.notes,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def list_for(
    db: Session,
    household_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    search: str | None = None,
) -> list[Transaction]:
    q = select(Transaction).where(Transaction.household_id == household_id)
    if account_id:
        q = q.where(Transaction.account_id == account_id)
    if since:
        q = q.where(Transaction.posted_at >= since)
    if until:
        q = q.where(Transaction.posted_at <= until)
    if search:
        q = q.where(Transaction.merchant_raw.ilike(f"%{search}%"))
    return list(db.scalars(q.order_by(Transaction.posted_at.desc())))


def get(db: Session, household_id: uuid.UUID, txn_id: uuid.UUID) -> Transaction | None:
    return db.scalar(
        select(Transaction).where(
            Transaction.id == txn_id, Transaction.household_id == household_id
        )
    )


def update(
    db: Session, household_id: uuid.UUID, txn_id: uuid.UUID, data: TxnUpdate
) -> Transaction | None:
    txn = get(db, household_id, txn_id)
    if not txn:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(txn, field, value)
    db.commit()
    db.refresh(txn)
    return txn


def delete(db: Session, household_id: uuid.UUID, txn_id: uuid.UUID) -> bool:
    txn = get(db, household_id, txn_id)
    if not txn:
        return False
    db.delete(txn)
    db.commit()
    return True
