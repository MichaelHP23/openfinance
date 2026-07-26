"""Investment view built from what a read-only bank feed actually provides.

SimpleFIN reports balances and transactions, not holdings — there are no share counts
or cost basis here, and none are invented. What it can honestly show is portfolio value,
the income those accounts throw off (dividends and interest), and what you put in.
Holdings-level detail needs a provider that carries it (Plaid Investments), which is
why this reads from the same DTOs as everything else rather than a special path.
"""

import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.transaction import Transaction

INVESTMENT_TYPES = {AccountType.investment, AccountType.crypto}

# Income a brokerage pays you, as it appears in transaction descriptions.
INCOME_HINTS = (
    "dividend",
    "div reinvest",
    "reinvestment",
    "interest",
    "int paid",
    "capital gain",
    "distribution",
    "qualified div",
)


def is_income(merchant: str) -> bool:
    text = merchant.lower()
    return any(hint in text for hint in INCOME_HINTS)


@dataclass
class MonthTotal:
    month: str
    total: float


@dataclass
class InvestmentSummary:
    total_value: float = 0.0
    account_count: int = 0
    accounts: list[dict[str, Any]] = field(default_factory=list)
    income_ytd: float = 0.0
    income_all_time: float = 0.0
    income_by_month: list[MonthTotal] = field(default_factory=list)
    recent_income: list[dict[str, Any]] = field(default_factory=list)
    contributions_ytd: float = 0.0
    # Dividends and interest are only visible if the feed happens to describe them that
    # way; a brokerage that reports them tersely will show nothing here.
    has_income_data: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(value: Decimal | float) -> float:
    return round(float(value), 2)


def summary(db: Session, household_id: uuid.UUID, months: int = 12) -> InvestmentSummary:
    now = datetime.now(UTC)
    out = InvestmentSummary()

    accounts = list(
        db.scalars(
            select(Account).where(
                Account.household_id == household_id, Account.type.in_(INVESTMENT_TYPES)
            )
        )
    )
    if not accounts:
        return out

    out.account_count = len(accounts)
    out.total_value = _f(sum((a.balance for a in accounts), start=Decimal(0)))

    by_id = {a.id: a for a in accounts}
    since = now - timedelta(days=31 * months)
    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.account_id.in_(list(by_id)),
                Transaction.posted_at >= since,
            )
        )
    )

    per_account_income: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    by_month: dict[str, Decimal] = defaultdict(Decimal)
    income_rows: list[tuple[datetime, str, str, Decimal]] = []

    for t in txns:
        merchant = t.merchant_normalized or t.merchant_raw
        if t.amount <= 0:
            continue
        if is_income(merchant):
            per_account_income[t.account_id] += t.amount
            by_month[t.posted_at.strftime("%Y-%m")] += t.amount
            income_rows.append((t.posted_at, by_id[t.account_id].name, merchant, t.amount))
            out.income_all_time += float(t.amount)
            if t.posted_at.year == now.year:
                out.income_ytd += float(t.amount)
        elif t.posted_at.year == now.year:
            # Money in that isn't described as income reads as a contribution.
            out.contributions_ytd += float(t.amount)

    out.income_ytd = round(out.income_ytd, 2)
    out.income_all_time = round(out.income_all_time, 2)
    out.contributions_ytd = round(out.contributions_ytd, 2)
    out.has_income_data = bool(income_rows)

    out.income_by_month = [MonthTotal(month=m, total=_f(v)) for m, v in sorted(by_month.items())]

    income_rows.sort(reverse=True)
    out.recent_income = [
        {
            "date": posted.date().isoformat(),
            "account": account_name,
            "merchant": merchant,
            "amount": _f(amount),
        }
        for posted, account_name, merchant, amount in income_rows[:10]
    ]

    out.accounts = [
        {
            "id": str(a.id),
            "name": a.name,
            "type": a.type.value,
            "balance": _f(a.balance),
            "income": _f(per_account_income.get(a.id, Decimal(0))),
            "share": round(float(a.balance) / float(out.total_value) * 100, 1)
            if out.total_value
            else 0.0,
        }
        for a in sorted(accounts, key=lambda a: a.balance, reverse=True)
    ]

    return out
