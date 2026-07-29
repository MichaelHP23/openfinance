"""Cost basis engine and holdings view — average cost, replay-based.

Average cost per **(security, account)** pair, not per security globally. A sale from a
taxable account must never be charged an average that includes shares bought inside an
IRA — see docs/superpowers/specs/2026-07-26-investments-trade-log-design.md §2.

Nothing here is cached. `positions()` replays every trade for the household on every
call.

# ponytail: the tripwire from the spec — if `trades` ever exceeds ~50,000 rows for one
# household, or the holdings endpoint p95 exceeds 300ms, add a `position_snapshots`
# table keyed on (security_id, account_id, as_of_month) and replay only from the last
# snapshot. A 20-year log at 4 trades/month is ~1,000 rows; do not build that now.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.security import Security
from app.models.security_price import SecurityPrice
from app.models.trade import Trade, TradeType


class InsufficientUnitsError(ValueError):
    """A sell trade would take a position below zero units. The API turns this into 422."""


@dataclass
class Position:
    units: Decimal = Decimal(0)  # shares held
    cost_base: Decimal = Decimal(0)  # total cost of those shares, in trade currency
    realized: Decimal = Decimal(0)  # cumulative realized gain
    dividends: Decimal = Decimal(0)  # cumulative cash dividends

    @property
    def avg_cost(self) -> Decimal:
        return self.cost_base / self.units if self.units else Decimal(0)


def _apply(pos: Position, trade: Trade) -> None:
    if trade.type == TradeType.buy:
        gross = trade.quantity * trade.price_per_unit
        pos.units += trade.quantity
        pos.cost_base += gross + trade.fees

    elif trade.type == TradeType.sell:
        if trade.quantity > pos.units:
            raise InsufficientUnitsError(
                f"Cannot sell {trade.quantity} units of security {trade.security_id} in "
                f"account {trade.account_id}: only {pos.units} held on {trade.traded_on}"
            )
        avg = pos.cost_base / pos.units if pos.units else Decimal(0)
        basis_sold = avg * trade.quantity
        proceeds = trade.quantity * trade.price_per_unit - trade.fees
        pos.realized += proceeds - basis_sold
        pos.cost_base -= basis_sold
        pos.units -= trade.quantity
        if pos.units == 0:
            # Numeric(19,8) division leaves crumbs — a fully-sold position must show
            # exactly zero cost base, not $0.0000003.
            pos.cost_base = Decimal(0)

    elif trade.type == TradeType.dividend:
        cash = (trade.quantity * trade.price_per_unit) if trade.quantity else trade.price_per_unit
        pos.dividends += cash
        # units and cost_base unchanged — a reinvested dividend is a separate buy row.

    elif trade.type == TradeType.split:
        # split_ratio is new-per-old: 2 for 2-for-1, 0.5 for a 1-for-2 reverse.
        # cost_base is untouched — a split creates no gain and consumes no money — so
        # avg_cost falls out correctly on its own.
        if trade.split_ratio is not None:
            pos.units *= trade.split_ratio


def positions(
    db: Session, household_id: uuid.UUID, as_of: date | None = None
) -> dict[tuple[uuid.UUID, uuid.UUID], Position]:
    """Replay every trade for the household, ordered `(traded_on, created_at)`.

    `created_at` is the tiebreaker so two same-day trades apply in entry order — this
    matters for a same-day buy-then-sell, and for a split entered after the buy it
    splits. Keyed by (security_id, account_id).
    """
    query = select(Trade).where(Trade.household_id == household_id)
    if as_of is not None:
        query = query.where(Trade.traded_on <= as_of)
    query = query.order_by(Trade.traded_on, Trade.created_at)

    out: dict[tuple[uuid.UUID, uuid.UUID], Position] = {}
    for trade in db.scalars(query):
        key = (trade.security_id, trade.account_id)
        pos = out.setdefault(key, Position())
        _apply(pos, trade)
    return out


def latest_price(
    db: Session, security_id: uuid.UUID, as_of: date | None = None
) -> SecurityPrice | None:
    """Most recent `security_prices` row on or before `as_of` (default: latest ever)."""
    query = select(SecurityPrice).where(SecurityPrice.security_id == security_id)
    if as_of is not None:
        query = query.where(SecurityPrice.priced_on <= as_of)
    query = query.order_by(SecurityPrice.priced_on.desc()).limit(1)
    return db.scalar(query)


@dataclass
class AccountUnits:
    account_id: uuid.UUID
    name: str
    units: Decimal


@dataclass
class Holding:
    security_id: uuid.UUID
    symbol: str
    name: str | None
    currency: str
    category: str | None  # always None until Phase 2
    units: Decimal
    avg_cost: Decimal
    cost_base: Decimal
    price: Decimal | None
    priced_on: date | None
    market_value: Decimal | None
    unrealized: Decimal | None
    unrealized_pct: Decimal | None
    dividends: Decimal
    share_pct: Decimal | None
    by_account: list[AccountUnits] = field(default_factory=list)


@dataclass
class HoldingsResult:
    holdings: list[Holding] = field(default_factory=list)
    totals: dict[str, Decimal] = field(default_factory=dict)
    priced_through: date | None = None


def holdings(db: Session, household_id: uuid.UUID, as_of: date | None = None) -> HoldingsResult:
    """Current holdings, one row per security, aggregated across every account.

    A security with zero total units (fully sold) is dropped from the list — this is a
    holdings view, not a trade log. Its dividends and realized history still exist in
    `positions()`, just not surfaced here.
    """
    pos_by_key = positions(db, household_id, as_of=as_of)
    if not pos_by_key:
        return HoldingsResult(
            totals={
                "cost_base": Decimal(0),
                "market_value": Decimal(0),
                "unrealized": Decimal(0),
                "dividends": Decimal(0),
            }
        )

    security_ids = {sec_id for sec_id, _ in pos_by_key}
    account_ids = {acct_id for _, acct_id in pos_by_key}
    securities = {
        s.id: s
        for s in db.scalars(
            select(Security).where(
                Security.household_id == household_id, Security.id.in_(security_ids)
            )
        )
    }
    accounts = {
        a.id: a
        for a in db.scalars(
            select(Account).where(Account.household_id == household_id, Account.id.in_(account_ids))
        )
    }

    # Aggregate per security across accounts.
    per_security: dict[uuid.UUID, dict[str, object]] = {}
    for (sec_id, acct_id), pos in pos_by_key.items():
        agg = per_security.setdefault(
            sec_id,
            {"units": Decimal(0), "cost_base": Decimal(0), "dividends": Decimal(0), "by_account": []},
        )
        agg["units"] += pos.units
        agg["cost_base"] += pos.cost_base
        agg["dividends"] += pos.dividends
        if pos.units != 0:
            account = accounts.get(acct_id)
            agg["by_account"].append(
                AccountUnits(account_id=acct_id, name=account.name if account else "", units=pos.units)
            )

    total_market_value = Decimal(0)
    total_cost_base = Decimal(0)
    total_unrealized = Decimal(0)
    total_dividends = Decimal(0)
    priced_through: date | None = None
    rows: list[Holding] = []

    for sec_id, agg in per_security.items():
        units = agg["units"]  # type: ignore[assignment]
        if units == 0:
            continue
        cost_base = agg["cost_base"]  # type: ignore[assignment]
        dividends = agg["dividends"]  # type: ignore[assignment]
        security = securities.get(sec_id)
        if security is None:
            continue

        price_row = latest_price(db, sec_id, as_of=as_of)
        price = price_row.close if price_row else None
        priced_on = price_row.priced_on if price_row else None

        if price is not None:
            market_value = units * price
            unrealized = market_value - cost_base
            # Percentage points (21.60, not 0.216) — matches HoldingOut's wire contract.
            unrealized_pct = (unrealized / cost_base * 100) if cost_base else None
            total_market_value += market_value
            total_unrealized += unrealized
            if priced_through is None or priced_on < priced_through:  # type: ignore[operator]
                priced_through = priced_on
        else:
            market_value = None
            unrealized = None
            unrealized_pct = None

        avg_cost = cost_base / units if units else Decimal(0)
        total_cost_base += cost_base
        total_dividends += dividends

        rows.append(
            Holding(
                security_id=sec_id,
                symbol=security.symbol,
                name=security.name,
                currency=security.currency,
                category=None,
                units=units,
                avg_cost=avg_cost,
                cost_base=cost_base,
                price=price,
                priced_on=priced_on,
                market_value=market_value,
                unrealized=unrealized,
                unrealized_pct=unrealized_pct,
                dividends=dividends,
                share_pct=None,  # filled below once the portfolio total is known
                by_account=sorted(agg["by_account"], key=lambda a: a.name),  # type: ignore[arg-type]
            )
        )

    for row in rows:
        if row.market_value is not None and total_market_value:
            row.share_pct = (row.market_value / total_market_value) * 100

    rows.sort(key=lambda r: r.symbol)

    return HoldingsResult(
        holdings=rows,
        totals={
            "cost_base": total_cost_base,
            "market_value": total_market_value,
            "unrealized": total_unrealized,
            "dividends": total_dividends,
        },
        priced_through=priced_through,
    )
