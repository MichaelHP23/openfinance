"""Pull accounts + transactions from a provider into the household's own rows.

Provider-agnostic on purpose: it takes anything satisfying `BankProvider`, so
SimpleFIN, Plaid, or a fake in tests all run the same path.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.connection import ConnStatus, ProviderConnection
from app.models.transaction import Transaction
from app.providers.base import BankProvider


@dataclass
class SyncResult:
    accounts_added: int = 0
    accounts_updated: int = 0
    transactions_added: int = 0
    transactions_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _account_type(raw: str) -> AccountType:
    try:
        return AccountType(raw)
    except ValueError:
        return AccountType.checking


def sync_connection(
    db: Session,
    household_id: uuid.UUID,
    conn: ProviderConnection,
    provider: BankProvider,
) -> SyncResult:
    if conn.household_id != household_id:
        raise ValueError("Connection belongs to another household")

    result = SyncResult()

    rows = list(
        db.scalars(
            select(Account).where(
                Account.household_id == household_id, Account.connection_id == conn.id
            )
        )
    )
    by_external = {a.external_id: a for a in rows if a.external_id}

    for account_dto in provider.fetch_accounts(conn):
        existing = by_external.get(account_dto.external_id)
        if existing:
            existing.name = account_dto.name
            existing.balance = account_dto.balance
            result.accounts_updated += 1
        else:
            created = Account(
                household_id=household_id,
                connection_id=conn.id,
                external_id=account_dto.external_id,
                type=_account_type(account_dto.type),
                name=account_dto.name,
                currency=account_dto.currency,
                balance=account_dto.balance,
                is_manual=False,
            )
            db.add(created)
            db.flush()
            by_external[account_dto.external_id] = created
            result.accounts_added += 1

    # Re-fetch from the last sync point; the provider decides what "since" means.
    txns = provider.fetch_transactions(conn, conn.last_synced_at)

    account_ids = [a.id for a in by_external.values()]
    seen: set[tuple[uuid.UUID, str]] = set()
    if account_ids:
        seen = {
            (account_id, external_id)
            for account_id, external_id in db.execute(
                select(Transaction.account_id, Transaction.external_id).where(
                    Transaction.account_id.in_(account_ids),
                    Transaction.external_id.is_not(None),
                )
            )
        }

    for txn_dto in txns:
        target = by_external.get(txn_dto.account_external_id)
        if target is None:
            # A transaction for an account the provider didn't list — nothing to hang it on.
            result.errors.append(f"Unknown account {txn_dto.account_external_id}")
            continue
        key = (target.id, txn_dto.external_id)
        if key in seen:
            result.transactions_skipped += 1
            continue
        db.add(
            Transaction(
                household_id=household_id,
                account_id=target.id,
                posted_at=txn_dto.posted_at,
                amount=txn_dto.amount,
                currency=txn_dto.currency,
                merchant_raw=txn_dto.merchant_raw,
                external_id=txn_dto.external_id,
            )
        )
        seen.add(key)
        result.transactions_added += 1

    conn.last_synced_at = datetime.now(UTC)
    conn.status = ConnStatus.active
    db.commit()
    return result
