import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.snapshot import BalanceSnapshot

# Types whose balance counts against you rather than for you.
LIABILITY_TYPES = {AccountType.credit_card, AccountType.loan, AccountType.liability}


@dataclass
class NetWorthPoint:
    on: date
    assets: Decimal
    debts: Decimal
    net: Decimal


def capture(db: Session, household_id: uuid.UUID, on: date | None = None) -> int:
    """Record today's balance for every account. Idempotent per (account, day)."""
    on = on or datetime.now(UTC).date()

    accounts = list(db.scalars(select(Account).where(Account.household_id == household_id)))
    if not accounts:
        return 0

    existing = {
        account_id
        for (account_id,) in db.execute(
            select(BalanceSnapshot.account_id).where(
                BalanceSnapshot.household_id == household_id,
                BalanceSnapshot.captured_on == on,
            )
        )
    }

    written = 0
    for account in accounts:
        if account.id in existing:
            # Re-running the same day overwrites, so the value tracks the latest sync.
            snapshot = db.scalar(
                select(BalanceSnapshot).where(
                    BalanceSnapshot.account_id == account.id,
                    BalanceSnapshot.captured_on == on,
                )
            )
            if snapshot:
                snapshot.balance = account.balance
                continue
        db.add(
            BalanceSnapshot(
                household_id=household_id,
                account_id=account.id,
                captured_on=on,
                balance=account.balance,
            )
        )
        written += 1

    db.commit()
    return written


def net_worth_series(db: Session, household_id: uuid.UUID, days: int = 90) -> list[NetWorthPoint]:
    """Net worth per captured day, oldest first."""
    since = datetime.now(UTC).date() - timedelta(days=days)

    rows = db.execute(
        select(BalanceSnapshot.captured_on, BalanceSnapshot.balance, Account.type)
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .where(
            BalanceSnapshot.household_id == household_id,
            BalanceSnapshot.captured_on >= since,
        )
        .order_by(BalanceSnapshot.captured_on)
    ).all()

    by_day: dict[date, list[Decimal]] = {}
    for captured_on, balance, account_type in rows:
        assets, debts = by_day.setdefault(captured_on, [Decimal(0), Decimal(0)])
        if account_type in LIABILITY_TYPES:
            by_day[captured_on] = [assets, debts + abs(balance)]
        else:
            by_day[captured_on] = [assets + balance, debts]

    return [
        NetWorthPoint(on=day, assets=assets, debts=debts, net=assets - debts)
        for day, (assets, debts) in sorted(by_day.items())
    ]
