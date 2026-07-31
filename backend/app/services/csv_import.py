import csv
import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.services import accounts, categorization


@dataclass
class ImportResult:
    imported: int
    skipped: int
    categorized: int = 0


def _external_id(date: str, amount: str, merchant: str) -> str:
    return hashlib.sha256(f"{date}|{amount}|{merchant}".encode()).hexdigest()


def import_csv(
    db: Session, household_id: uuid.UUID, account_id: uuid.UUID, raw: str
) -> ImportResult:
    if accounts.get(db, household_id, account_id) is None:
        raise ValueError("Account not in household")
    existing = set(
        db.scalars(select(Transaction.external_id).where(Transaction.account_id == account_id))
    )
    imported = skipped = 0
    added: list[Transaction] = []
    for row in csv.DictReader(io.StringIO(raw)):
        ext = _external_id(row["date"], row["amount"], row["merchant"])
        if ext in existing:
            skipped += 1
            continue
        txn = Transaction(
            household_id=household_id,
            account_id=account_id,
            posted_at=datetime.fromisoformat(row["date"]).replace(tzinfo=UTC),
            amount=Decimal(row["amount"]),
            currency="USD",
            merchant_raw=row["merchant"],
            external_id=ext,
        )
        db.add(txn)
        added.append(txn)
        existing.add(ext)
        imported += 1
    # Categorize before the commit so an import is one transaction: either the rows and
    # their categories land together, or neither does.
    categorized = categorization.apply_to(db, household_id, added)
    db.commit()
    return ImportResult(imported=imported, skipped=skipped, categorized=categorized)
