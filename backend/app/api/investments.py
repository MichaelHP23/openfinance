"""`/investments/*` — securities, trades, holdings, and manual price overrides.

Thin by design: every rule (cost basis, over-sell rejection, symbol resolution,
manual-price precedence) already lives in `app/services/{securities,portfolio,
trades,prices}.py`. This module only does household scoping, request/response
shaping against `app/schemas/investment.py`, and turning service exceptions into
4xx responses.

NOTE: `/investments` and `/investments/history` are defined in `api/insights.py`
(portfolio summary + snapshot history) — this router deliberately never defines
those two paths, only the more specific ones below it.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.security import Security
from app.models.trade import Trade
from app.schemas.investment import (
    AccountUnitsOut,
    HoldingOut,
    HoldingsOut,
    HoldingsTotals,
    ImportResultOut,
    PriceIn,
    SecurityOut,
    TradeIn,
    TradeOut,
    TradesOut,
)
from app.services import portfolio
from app.services import prices as prices_service
from app.services import securities as securities_service
from app.services import trade_import
from app.services import trades as trades_service

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("/securities", response_model=list[SecurityOut])
def list_securities(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[Security]:
    return securities_service.list_for(db, hid)


def _account_units_out(a: portfolio.AccountUnits) -> AccountUnitsOut:
    return AccountUnitsOut(account_id=a.account_id, name=a.name, units=a.units)


def _holding_out(h: portfolio.Holding) -> HoldingOut:
    return HoldingOut(
        security_id=h.security_id,
        symbol=h.symbol,
        name=h.name,
        currency=h.currency,
        category=h.category,
        units=h.units,
        avg_cost=h.avg_cost,
        cost_base=h.cost_base,
        price=h.price,
        priced_on=h.priced_on,
        market_value=h.market_value,
        unrealized=h.unrealized,
        unrealized_pct=h.unrealized_pct,
        dividends=h.dividends,
        share_pct=h.share_pct,
        by_account=[_account_units_out(a) for a in h.by_account],
    )


@router.get("/holdings", response_model=HoldingsOut)
def list_holdings(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> HoldingsOut:
    result = portfolio.holdings(db, hid)
    return HoldingsOut(
        holdings=[_holding_out(h) for h in result.holdings],
        totals=HoldingsTotals(**result.totals),
        priced_through=result.priced_through,
    )


def _trade_out(t: Trade, symbol: str) -> TradeOut:
    return TradeOut(
        id=t.id,
        account_id=t.account_id,
        security_id=t.security_id,
        symbol=symbol,
        traded_on=t.traded_on,
        type=t.type,
        quantity=t.quantity,
        price_per_unit=t.price_per_unit,
        fees=t.fees,
        split_ratio=t.split_ratio,
        currency=t.currency,
        notes=t.notes,
    )


def _symbols_by_security_id(db: Session, hid: uuid.UUID, rows: list[Trade]) -> dict[uuid.UUID, str]:
    sec_ids = {t.security_id for t in rows}
    if not sec_ids:
        return {}
    return {
        s.id: s.symbol
        for s in db.scalars(
            select(Security).where(Security.household_id == hid, Security.id.in_(sec_ids))
        )
    }


@router.get("/trades", response_model=TradesOut)
def list_trades(
    security_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    limit: int = 200,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> TradesOut:
    rows, total = trades_service.list_for(
        db,
        hid,
        security_id=security_id,
        account_id=account_id,
        since=from_,
        until=to,
        limit=limit,
    )
    symbols = _symbols_by_security_id(db, hid, rows)
    return TradesOut(
        trades=[_trade_out(t, symbols.get(t.security_id, "")) for t in rows], total=total
    )


@router.post("/trades", response_model=TradeOut)
def create_trade(
    body: TradeIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> TradeOut:
    try:
        created = trades_service.create(db, hid, body)
    except trades_service.AccountNotInHousehold:
        raise HTTPException(status_code=404, detail="Account not found")
    except portfolio.InsufficientUnitsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _trade_out(created[0], body.symbol.strip().upper())


@router.post("/trades/import", response_model=ImportResultOut)
async def import_trades(
    file: UploadFile,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> ImportResultOut:
    raw = await file.read()
    try:
        result = trade_import.import_csv(db, hid, raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ImportResultOut(imported=result.imported, skipped=result.skipped, errors=result.errors)


@router.delete("/trades/{trade_id}")
def delete_trade(
    trade_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        deleted = trades_service.delete(db, hid, trade_id)
    except portfolio.InsufficientUnitsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"status": "ok"}


@router.post("/prices")
def set_price(
    body: PriceIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if securities_service.get(db, hid, body.security_id) is None:
        raise HTTPException(status_code=404, detail="Security not found")
    prices_service.set_manual_price(db, body.security_id, body.priced_on, body.close)
    return {"status": "ok"}
