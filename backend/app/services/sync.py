"""Pull accounts + transactions from a provider into the household's own rows.

Provider-agnostic on purpose: it takes anything satisfying `BankProvider`, so
SimpleFIN, Plaid, or a fake in tests all run the same path.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.connection import ConnStatus, ProviderConnection
from app.models.transaction import Transaction
from app.providers.base import BankProvider, TxnDTO

INITIAL_HISTORY_DAYS = 365


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
    *,
    full: bool = False,
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

    # First sync pulls a year; without an explicit window SimpleFIN returns only a
    # handful of recent days, which is not enough to show trends or spot subscriptions.
    year_ago = datetime.now(UTC) - timedelta(days=INITIAL_HISTORY_DAYS)
    since = year_ago if full or conn.last_synced_at is None else conn.last_synced_at
    txns = provider.fetch_transactions(conn, since)

    account_ids = [a.id for a in by_external.values()]
    seen: set[tuple[uuid.UUID, str]] = set()
    # Second line of defence: how many rows we already hold per identical-looking
    # transaction. Providers do re-issue ids — a pending charge gets a new one when it
    # posts, and SimpleFIN's demo re-ids everything on every call — so matching on
    # external_id alone silently multiplies rows on each sync. Counting means two genuinely
    # identical purchases still both survive: the provider reports two, so we keep two.
    held: Counter[tuple[uuid.UUID, date, Decimal, str]] = Counter()
    if account_ids:
        for account_id, external_id, posted_at, amount, merchant in db.execute(
            select(
                Transaction.account_id,
                Transaction.external_id,
                Transaction.posted_at,
                Transaction.amount,
                Transaction.merchant_raw,
            ).where(Transaction.account_id.in_(account_ids))
        ):
            if external_id is not None:
                seen.add((account_id, external_id))
            held[(account_id, posted_at.date(), amount, merchant)] += 1

    def _shape(account_id: uuid.UUID, dto: TxnDTO) -> tuple[uuid.UUID, date, Decimal, str]:
        return (account_id, dto.posted_at.date(), dto.amount, dto.merchant_raw)

    # Rows we can match by id are accounted for first, so they don't also consume a
    # count slot and let a genuine new transaction through as a "duplicate".
    resolved: list[TxnDTO] = []
    for txn_dto in txns:
        target = by_external.get(txn_dto.account_external_id)
        if target is None:
            # A transaction for an account the provider didn't list — nothing to hang it on.
            result.errors.append(f"Unknown account {txn_dto.account_external_id}")
            continue
        if (target.id, txn_dto.external_id) in seen:
            result.transactions_skipped += 1
            held[_shape(target.id, txn_dto)] -= 1
            continue
        resolved.append(txn_dto)

    for txn_dto in resolved:
        target = by_external[txn_dto.account_external_id]
        shape = _shape(target.id, txn_dto)
        if held[shape] > 0:
            # Same account, day, amount and merchant as a row we already hold, under a
            # different id — treat it as the one we have rather than a second charge.
            held[shape] -= 1
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
        seen.add((target.id, txn_dto.external_id))
        result.transactions_added += 1

    conn.last_synced_at = datetime.now(UTC)
    conn.status = ConnStatus.active
    db.commit()
    return result
