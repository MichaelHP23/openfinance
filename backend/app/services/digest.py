"""A factual snapshot of a household's finances.

Every number here is computed from the database. The LLM assistant is handed this
digest and asked to interpret it — it never queries anything itself and never
produces a figure of its own. That's the "never hallucinate numbers" constraint:
arithmetic is the app's job, phrasing is the model's.
"""

import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction
from app.services import investments as investments_service
from app.services.snapshots import LIABILITY_TYPES, net_worth_series


@dataclass
class MerchantTotal:
    merchant: str
    total: float
    count: int


@dataclass
class MonthTotals:
    month: str
    income: float
    spending: float
    net: float


@dataclass
class Digest:
    generated_at: str
    currency: str = "USD"
    net_worth: float = 0.0
    assets: float = 0.0
    debts: float = 0.0
    net_worth_change_30d: float | None = None
    accounts: list[dict[str, Any]] = field(default_factory=list)
    months: list[MonthTotals] = field(default_factory=list)
    top_merchants: list[MerchantTotal] = field(default_factory=list)
    largest_transactions: list[dict[str, Any]] = field(default_factory=list)
    recurring_candidates: list[dict[str, Any]] = field(default_factory=list)
    transaction_count: int = 0
    oldest_transaction: str | None = None
    investments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(value: Decimal | float) -> float:
    return round(float(value), 2)


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def build(db: Session, household_id: uuid.UUID, months_back: int = 6) -> Digest:
    now = datetime.now(UTC)
    digest = Digest(generated_at=now.isoformat())

    accounts = list(db.scalars(select(Account).where(Account.household_id == household_id)))
    assets = sum((a.balance for a in accounts if a.type not in LIABILITY_TYPES), start=Decimal(0))
    debts = sum((abs(a.balance) for a in accounts if a.type in LIABILITY_TYPES), start=Decimal(0))
    digest.assets = _f(assets)
    digest.debts = _f(debts)
    digest.net_worth = _f(assets - debts)
    digest.accounts = [
        {
            "name": a.name,
            "type": a.type.value,
            "balance": _f(a.balance),
            "is_liability": a.type in LIABILITY_TYPES,
            "linked": not a.is_manual,
        }
        for a in accounts
    ]

    series = net_worth_series(db, household_id, days=30)
    if len(series) >= 2:
        digest.net_worth_change_30d = _f(series[-1].net - series[0].net)

    since = now - timedelta(days=31 * months_back)
    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id, Transaction.posted_at >= since
            )
        )
    )
    digest.transaction_count = len(txns)
    if txns:
        digest.oldest_transaction = min(t.posted_at for t in txns).date().isoformat()

    by_month: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    merchant_totals: dict[str, list[Decimal | int]] = defaultdict(lambda: [Decimal(0), 0])
    for t in txns:
        income, spending = by_month[_month_key(t.posted_at)]
        if t.amount >= 0:
            by_month[_month_key(t.posted_at)] = [income + t.amount, spending]
        else:
            by_month[_month_key(t.posted_at)] = [income, spending + -t.amount]
            name = t.merchant_normalized or t.merchant_raw
            total, count = merchant_totals[name]
            merchant_totals[name] = [Decimal(total) + -t.amount, int(count) + 1]

    digest.months = [
        MonthTotals(month=m, income=_f(inc), spending=_f(spend), net=_f(inc - spend))
        for m, (inc, spend) in sorted(by_month.items())
    ]

    ranked = sorted(merchant_totals.items(), key=lambda kv: kv[1][0], reverse=True)
    digest.top_merchants = [
        MerchantTotal(merchant=name, total=_f(Decimal(total)), count=int(count))
        for name, (total, count) in ranked[:12]
    ]

    digest.largest_transactions = [
        {
            "date": t.posted_at.date().isoformat(),
            "merchant": t.merchant_normalized or t.merchant_raw,
            "amount": _f(t.amount),
        }
        for t in sorted(txns, key=lambda t: t.amount)[:8]
    ]

    # A merchant charged a similar amount in 3+ distinct months looks like a subscription.
    for name, (_total, count) in ranked:
        charges = [t for t in txns if (t.merchant_normalized or t.merchant_raw) == name]
        months_seen = {_month_key(t.posted_at) for t in charges}
        amounts = {_f(abs(t.amount)) for t in charges}
        if len(months_seen) >= 3 and len(amounts) <= 2 and int(count) >= 3:
            digest.recurring_candidates.append(
                {
                    "merchant": name,
                    "typical_amount": max(amounts),
                    "months_seen": len(months_seen),
                }
            )

    invest = investments_service.summary(db, household_id)
    digest.investments = {
        "total_value": invest.total_value,
        "account_count": invest.account_count,
        "income_ytd": invest.income_ytd,
        "contributions_ytd": invest.contributions_ytd,
        "accounts": invest.accounts,
    }

    return digest
