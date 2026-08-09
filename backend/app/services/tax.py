"""FIFO realized-gains engine over the existing trade log (`models/trade.py`). Keyed
per (security_id, account_id), same boundary as `services/portfolio.py`'s average
cost — a separate, from-scratch replay because average cost and lot-by-lot FIFO are
different methods for different questions, not two implementations of one.

Wash-sale detection is cut (design spec, P5) — `export_csv` (Task 4) says so on its
face. This app's `AccountType` (models/account.py) has no taxable-vs-retirement
distinction, so realized gains here cover every sell trade; see this plan's recorded
deviation for why that's a reporting-tool limitation, not a bug.
"""

import csv
import io
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security import Security
from app.models.trade import Trade, TradeType
from app.models.transaction import Transaction
from app.services.categories import system_category_id

LONG_TERM_DAYS = 365

CENTS = Decimal("0.01")


def _money(d: Decimal) -> Decimal:
    """Round a dollar figure to cents, the way every other money field in this codebase
    leaves its service (`reports.py`, `recurring.py`, `forecast.py`).

    `Trade.quantity`/`price_per_unit` are `NUMERIC(19, 8)` — after a DB round-trip,
    multiplying/dividing them balloons a clean `200` into `Decimal("200.0000000000000000")`.
    Always quantizing to cents keeps this field's serialized shape ("200.00") consistent
    with every other money field this plan's endpoints return, rather than varying by
    whether the value happens to be a whole dollar.
    """
    return d.quantize(CENTS)


@dataclass
class _Lot:
    quantity: Decimal
    cost_per_unit: Decimal
    opened_on: date


@dataclass
class RealizedGain:
    security_id: uuid.UUID
    symbol: str
    account_id: uuid.UUID
    opened_on: date
    closed_on: date
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    gain: Decimal
    term: str  # "short" | "long"


@dataclass
class RealizedGainsResult:
    year: int
    gains: list[RealizedGain] = field(default_factory=list)
    short_term_gain: Decimal = Decimal(0)
    long_term_gain: Decimal = Decimal(0)
    total_gain: Decimal = Decimal(0)


def _replay(trades: list[Trade], symbols: dict[uuid.UUID, str]) -> list[RealizedGain]:
    lots: dict[tuple[uuid.UUID, uuid.UUID], deque[_Lot]] = defaultdict(deque)
    gains: list[RealizedGain] = []

    for t in trades:
        key = (t.security_id, t.account_id)

        if t.type == TradeType.buy:
            if not t.quantity:
                continue
            cost_per_unit = (t.quantity * t.price_per_unit + t.fees) / t.quantity
            lots[key].append(_Lot(quantity=t.quantity, cost_per_unit=cost_per_unit, opened_on=t.traded_on))

        elif t.type == TradeType.sell:
            if not t.quantity:
                continue
            proceeds_per_unit = (t.quantity * t.price_per_unit - t.fees) / t.quantity
            remaining = t.quantity
            queue = lots[key]
            while remaining > 0 and queue:
                lot = queue[0]
                take = min(lot.quantity, remaining)
                cost_basis = _money(take * lot.cost_per_unit)
                proceeds = _money(take * proceeds_per_unit)
                term = "long" if (t.traded_on - lot.opened_on).days > LONG_TERM_DAYS else "short"
                gains.append(
                    RealizedGain(
                        security_id=t.security_id,
                        symbol=symbols.get(t.security_id, "?"),
                        account_id=t.account_id,
                        opened_on=lot.opened_on,
                        closed_on=t.traded_on,
                        quantity=take,
                        proceeds=proceeds,
                        cost_basis=cost_basis,
                        gain=_money(proceeds - cost_basis),
                        term=term,
                    )
                )
                lot.quantity -= take
                remaining -= take
                if lot.quantity == 0:
                    queue.popleft()
            # A sell that outruns every open lot (remaining > 0 here) would mean the
            # trade log itself is inconsistent. trades.py already refuses to write a
            # sell that goes negative (`portfolio.InsufficientUnitsError`), so every
            # sell this function ever sees has enough recorded units to fully match.

        elif t.type == TradeType.split and t.split_ratio:
            # New-per-old, same as portfolio.py: units scale up and cost per unit
            # scales down by the same factor, so total cost basis is unchanged by the
            # split itself, and the lot's opened_on — its holding period — is untouched.
            for lot in lots[key]:
                lot.quantity *= t.split_ratio
                lot.cost_per_unit /= t.split_ratio

        # dividend: no lot effect. Dividend income is covered by `income_summary`
        # (Task 4), from categorized transactions, not from the trade log — see this
        # plan's recorded deviation on why the two sources aren't both read here.

    return gains


def realized_gains(db: Session, household_id: uuid.UUID, year: int) -> RealizedGainsResult:
    trades = list(
        db.scalars(
            select(Trade).where(Trade.household_id == household_id).order_by(Trade.traded_on, Trade.created_at)
        )
    )
    symbols = {s.id: s.symbol for s in db.scalars(select(Security).where(Security.household_id == household_id))}
    all_gains = _replay(trades, symbols)
    year_gains = sorted((g for g in all_gains if g.closed_on.year == year), key=lambda g: g.closed_on)
    short = _money(sum((g.gain for g in year_gains if g.term == "short"), Decimal(0)))
    long_ = _money(sum((g.gain for g in year_gains if g.term == "long"), Decimal(0)))
    return RealizedGainsResult(
        year=year, gains=year_gains, short_term_gain=short, long_term_gain=long_, total_gain=_money(short + long_)
    )


@dataclass
class IncomeSummary:
    year: int
    dividends: Decimal
    interest: Decimal
    total: Decimal


def income_summary(db: Session, household_id: uuid.UUID, year: int) -> IncomeSummary:
    """Dividends and interest, both read from categorized transactions (P1's system
    taxonomy) rather than from the trade log's own `dividend` TradeType — a household's
    brokerage dividend usually also lands as a bank-fed transaction row, and reading it
    from both places would double it. `realized_gains` above is the only place this
    phase reads `models/trade.py` directly."""
    dividends_id = system_category_id("Income/Dividends")
    interest_id = system_category_id("Income/Interest")
    since = datetime(year, 1, 1, tzinfo=UTC)
    until = datetime(year + 1, 1, 1, tzinfo=UTC)

    txns = db.scalars(
        select(Transaction).where(
            Transaction.household_id == household_id,
            Transaction.category_id.in_([dividends_id, interest_id]),
            Transaction.posted_at >= since,
            Transaction.posted_at < until,
        )
    )
    dividends = Decimal(0)
    interest = Decimal(0)
    for t in txns:
        if t.category_id == dividends_id:
            dividends += t.amount
        elif t.category_id == interest_id:
            interest += t.amount
    # Quantized to cents before leaving the service: Transaction.amount is NUMERIC(19,4),
    # which round-trips through the ORM with four decimal places (see reports.py's
    # income_vs_expense for the same fix).
    dividends = _money(dividends)
    interest = _money(interest)
    return IncomeSummary(year=year, dividends=dividends, interest=interest, total=_money(dividends + interest))


WASH_SALE_DISCLAIMER = (
    "This export does not detect or adjust for wash sales. If a security was sold at a "
    "loss and a substantially identical one bought within 30 days, the real deductible "
    "loss may be lower than the figure below. This is a reporting tool only — confirm "
    "with a tax professional before filing."
)


def export_csv(db: Session, household_id: uuid.UUID, year: int) -> str:
    """A Schedule-D-shaped CSV: one row per matched lot, then short/long totals. A
    starting point to paste from, not a filing document."""
    result = realized_gains(db, household_id, year)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([f"# {WASH_SALE_DISCLAIMER}"])
    writer.writerow(
        ["Symbol", "Account", "Date acquired", "Date sold", "Proceeds", "Cost basis", "Gain/loss", "Term"]
    )
    for g in result.gains:
        writer.writerow(
            [g.symbol, str(g.account_id), g.opened_on.isoformat(), g.closed_on.isoformat(),
             str(g.proceeds), str(g.cost_basis), str(g.gain), g.term]
        )
    writer.writerow([])
    writer.writerow(["Short-term total", str(result.short_term_gain)])
    writer.writerow(["Long-term total", str(result.long_term_gain)])
    writer.writerow(["Total", str(result.total_gain)])
    return out.getvalue()
