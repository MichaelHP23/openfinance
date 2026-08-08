import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.snapshot import BalanceSnapshot
from app.models.transaction import Transaction
from app.schemas.account import AccountCreate, AccountUpdate

SUPPORTED_CURRENCY = "USD"


def create(db: Session, household_id: uuid.UUID, data: AccountCreate) -> Account:
    if data.currency != SUPPORTED_CURRENCY:
        raise ValueError("Only USD supported in v1")
    acct = Account(
        household_id=household_id,
        type=AccountType(data.type),
        name=data.name,
        institution=data.institution,
        currency=data.currency,
        balance=data.balance,
        is_manual=True,
        beneficiary=data.beneficiary,
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


def update(
    db: Session, household_id: uuid.UUID, account_id: uuid.UUID, data: AccountUpdate
) -> Account | None:
    """Correct an account's details.

    Type especially: provider names rarely say "credit card", so a card can land as
    checking and quietly count as an asset. The user has to be able to fix that.
    """
    account = get(db, household_id, account_id)
    if account is None:
        return None

    fields = data.model_dump(exclude_unset=True, exclude_none=True)
    if "type" in fields:
        try:
            account.type = AccountType(fields.pop("type"))
        except ValueError as exc:
            raise ValueError(f"Unknown account type: {data.type}") from exc
    for field, value in fields.items():
        setattr(account, field, value)

    db.commit()
    db.refresh(account)
    return account


def delete(db: Session, household_id: uuid.UUID, account_id: uuid.UUID) -> bool:
    """Remove an account and everything hanging off it.

    Transactions and snapshots are meaningless without their account, so they go too —
    this is the only way to undo a mistyped account or clear out demo data.
    """
    account = get(db, household_id, account_id)
    if account is None:
        return False

    db.query(BalanceSnapshot).filter(BalanceSnapshot.account_id == account_id).delete()
    db.query(Transaction).filter(Transaction.account_id == account_id).delete()
    db.delete(account)
    db.commit()
    return True
