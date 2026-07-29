"""CRUD for the trade log itself. Every write re-runs the cost basis replay
(`portfolio.positions`) before committing — an edit or delete that would leave a sell
selling more units than were ever held is rejected and rolled back, wherever in the date
order the change lands. This is what "a wrong row is fixed by editing the row" requires:
the replay, not the write, is the source of truth for validity.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.trade import Trade, TradeType
from app.schemas.investment import TradeIn, TradeUpdate
from app.services import portfolio, securities


class AccountNotInHousehold(ValueError):
    pass


def _assert_account(db: Session, household_id: uuid.UUID, account_id: uuid.UUID) -> None:
    exists = db.scalar(
        select(Account.id).where(Account.id == account_id, Account.household_id == household_id)
    )
    if exists is None:
        raise AccountNotInHousehold(str(account_id))


def _resolve_dividend_amount(
    type_: TradeType, quantity: Decimal, price_per_unit: Decimal, amount: Decimal | None
) -> tuple[Decimal, Decimal]:
    """Dividend convenience: accept a total `amount` when the per-unit rate is unknown.

    quantity known -> price_per_unit = amount / quantity.
    quantity unknown (0) -> quantity stays 0, price_per_unit carries the whole payment.
    Only applies to dividends; buy/sell always require quantity and price_per_unit.
    """
    if type_ != TradeType.dividend or amount is None:
        return quantity, price_per_unit
    if quantity:
        return quantity, amount / quantity
    return Decimal(0), amount


def _validate_replay(db: Session, household_id: uuid.UUID) -> None:
    portfolio.positions(db, household_id)  # raises InsufficientUnitsError on a bad sell


def get(db: Session, household_id: uuid.UUID, trade_id: uuid.UUID) -> Trade | None:
    return db.scalar(
        select(Trade).where(Trade.id == trade_id, Trade.household_id == household_id)
    )


def list_for(
    db: Session,
    household_id: uuid.UUID,
    *,
    security_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = 200,
) -> tuple[list[Trade], int]:
    q = select(Trade).where(Trade.household_id == household_id)
    if security_id:
        q = q.where(Trade.security_id == security_id)
    if account_id:
        q = q.where(Trade.account_id == account_id)
    if since:
        q = q.where(Trade.traded_on >= since)
    if until:
        q = q.where(Trade.traded_on <= until)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(
        db.scalars(q.order_by(Trade.traded_on.desc(), Trade.created_at.desc()).limit(limit))
    )
    return rows, total


def create(db: Session, household_id: uuid.UUID, data: TradeIn) -> list[Trade]:
    """Insert one trade, or — for a split with `account_id=None` — one row per account
    currently holding the security (spec §2.3's fan-out, so a split affecting three
    accounts doesn't need three separate manual entries).

    Returns the trade(s) created. Raises `AccountNotInHousehold`, `ValueError` (no
    account holds the security to split, or account_id missing on a non-split), or
    `portfolio.InsufficientUnitsError` (the replay went negative) — nothing is left
    committed on any of these.
    """
    security = securities.get_or_create(db, household_id, data.symbol, data.currency)
    quantity, price_per_unit = _resolve_dividend_amount(
        data.type, data.quantity, data.price_per_unit, data.amount
    )

    if data.type == TradeType.split and data.account_id is None:
        pos = portfolio.positions(db, household_id)
        account_ids = sorted(
            {
                acct_id
                for (sec_id, acct_id), p in pos.items()
                if sec_id == security.id and p.units > 0
            },
            key=str,
        )
        if not account_ids:
            raise ValueError(f"No account currently holds {security.symbol} to split")
        targets = account_ids
    else:
        if data.account_id is None:
            raise ValueError("account_id is required except for a split")
        _assert_account(db, household_id, data.account_id)
        targets = [data.account_id]

    new_trades = [
        Trade(
            household_id=household_id,
            account_id=acct_id,
            security_id=security.id,
            traded_on=data.traded_on,
            type=data.type,
            quantity=quantity,
            price_per_unit=price_per_unit,
            fees=data.fees,
            split_ratio=data.split_ratio,
            currency=data.currency,
            notes=data.notes,
            external_id=data.external_id,
        )
        for acct_id in targets
    ]
    with db.begin_nested():
        db.add_all(new_trades)
        db.flush()
        _validate_replay(db, household_id)
    db.commit()
    for t in new_trades:
        db.refresh(t)
    return new_trades


def update(
    db: Session, household_id: uuid.UUID, trade_id: uuid.UUID, data: TradeUpdate
) -> Trade | None:
    trade = get(db, household_id, trade_id)
    if trade is None:
        return None

    fields = data.model_dump(exclude_unset=True)
    amount = fields.pop("amount", None)
    if fields.get("account_id") is not None:
        _assert_account(db, household_id, fields["account_id"])

    with db.begin_nested():
        for field, value in fields.items():
            setattr(trade, field, value)
        if amount is not None:
            trade.quantity, trade.price_per_unit = _resolve_dividend_amount(
                trade.type, trade.quantity, trade.price_per_unit, amount
            )
        db.flush()
        _validate_replay(db, household_id)
    db.commit()
    db.refresh(trade)
    return trade


def delete(db: Session, household_id: uuid.UUID, trade_id: uuid.UUID) -> bool:
    trade = get(db, household_id, trade_id)
    if trade is None:
        return False
    with db.begin_nested():
        db.delete(trade)
        db.flush()
        _validate_replay(db, household_id)
    db.commit()
    return True
