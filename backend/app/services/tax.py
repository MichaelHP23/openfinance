"""FIFO realized-gains engine over the existing trade log (`models/trade.py`). Keyed
per (security_id, account_id), same boundary as `services/portfolio.py`'s average
cost — a separate, from-scratch replay because average cost and lot-by-lot FIFO are
different methods for different questions, not two implementations of one.

Wash-sale detection is cut (design spec, P5) — `export_csv` (Task 4) says so on its
face. This app's `AccountType` (models/account.py) has no taxable-vs-retirement
distinction, so realized gains here cover every sell trade; see this plan's recorded
deviation for why that's a reporting-tool limitation, not a bug.
"""

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security import Security
from app.models.trade import Trade, TradeType

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
