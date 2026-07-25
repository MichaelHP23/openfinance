import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.account import Account, AccountType
from app.schemas.account import AccountCreate

SUPPORTED_CURRENCY = "USD"


def create(db: Session, household_id: uuid.UUID, data: AccountCreate) -> Account:
    if data.currency != SUPPORTED_CURRENCY:
        raise ValueError("Only USD supported in v1")
    acct = Account(
        household_id=household_id, type=AccountType(data.type), name=data.name,
        institution=data.institution, currency=data.currency, balance=data.balance,
        is_manual=True,
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def list_for(db: Session, household_id: uuid.UUID) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.household_id == household_id)))


def get(db: Session, household_id: uuid.UUID, account_id: uuid.UUID) -> Account | None:
    return db.scalar(
        select(Account).where(Account.id == account_id, Account.household_id == household_id)
    )
