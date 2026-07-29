import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.trade import TradeType
from app.schemas.investment import SecurityCreate, TradeIn, TradeUpdate
from app.services import portfolio, securities, trades


def _household(db) -> uuid.UUID:
    h = Household(name="Trades Household")
    db.add(h)
    db.commit()
    return h.id


def _account(db, hid, name="Brokerage") -> Account:
    a = Account(household_id=hid, type=AccountType.investment, name=name, balance=Decimal(0))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_create_trade_resolves_symbol_and_creates_security_if_unknown(db):
    hid = _household(db)
    acct = _account(db, hid)
    created = trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="vti",
            traded_on=date(2026, 3, 1),
            type=TradeType.buy,
            quantity=Decimal("10"),
            price_per_unit=Decimal("241.30"),
        ),
    )
    assert len(created) == 1
    sec = securities.get_by_symbol(db, hid, "VTI")
    assert sec is not None
    assert created[0].security_id == sec.id


def test_create_reuses_existing_security(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = securities.create(db, hid, SecurityCreate(symbol="VTI"))
    created = trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="vti",
            traded_on=date(2026, 3, 1),
            type=TradeType.buy,
            quantity=Decimal("1"),
            price_per_unit=Decimal("1"),
        ),
    )
    assert created[0].security_id == sec.id


def test_create_rejects_unknown_account(db):
    hid = _household(db)
    with pytest.raises(trades.AccountNotInHousehold):
        trades.create(
            db,
            hid,
            TradeIn(
                account_id=uuid.uuid4(),
                symbol="VTI",
                traded_on=date(2026, 3, 1),
                type=TradeType.buy,
                quantity=Decimal("1"),
                price_per_unit=Decimal("1"),
            ),
        )


def test_create_sell_exceeding_units_raises_and_rolls_back(db):
    hid = _household(db)
    acct = _account(db, hid)
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 1, 1),
            type=TradeType.buy,
            quantity=Decimal("5"),
            price_per_unit=Decimal("10"),
        ),
    )
    with pytest.raises(portfolio.InsufficientUnitsError):
        trades.create(
            db,
            hid,
            TradeIn(
                account_id=acct.id,
                symbol="VTI",
                traded_on=date(2026, 1, 2),
                type=TradeType.sell,
                quantity=Decimal("6"),
                price_per_unit=Decimal("10"),
            ),
        )
    rows, total = trades.list_for(db, hid)
    assert total == 1  # the bad sell never landed


def test_dividend_amount_convenience_resolves_price_per_unit(db):
    hid = _household(db)
    acct = _account(db, hid)
    created = trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 3, 1),
            type=TradeType.dividend,
            quantity=Decimal("10"),
            amount=Decimal("5.00"),
        ),
    )
    assert created[0].price_per_unit == Decimal("0.50")


def test_dividend_amount_with_unknown_quantity(db):
    hid = _household(db)
    acct = _account(db, hid)
    created = trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 3, 1),
            type=TradeType.dividend,
            amount=Decimal("12.34"),
        ),
    )
    assert created[0].quantity == Decimal("0")
    assert created[0].price_per_unit == Decimal("12.34")


def test_split_with_null_account_fans_out_to_every_holding_account(db):
    hid = _household(db)
    acct1 = _account(db, hid, "Roth")
    acct2 = _account(db, hid, "Taxable")
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct1.id,
            symbol="VTI",
            traded_on=date(2026, 1, 1),
            type=TradeType.buy,
            quantity=Decimal("10"),
            price_per_unit=Decimal("100"),
        ),
    )
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct2.id,
            symbol="VTI",
            traded_on=date(2026, 1, 1),
            type=TradeType.buy,
            quantity=Decimal("5"),
            price_per_unit=Decimal("100"),
        ),
    )
    created = trades.create(
        db,
        hid,
        TradeIn(
            account_id=None,
            symbol="VTI",
            traded_on=date(2026, 2, 1),
            type=TradeType.split,
            split_ratio=Decimal("2"),
        ),
    )
    assert len(created) == 2
    pos = portfolio.positions(db, hid)
    sec = securities.get_by_symbol(db, hid, "VTI")
    assert pos[(sec.id, acct1.id)].units == Decimal("20")
    assert pos[(sec.id, acct2.id)].units == Decimal("10")


def test_split_with_null_account_and_no_holders_raises(db):
    hid = _household(db)
    securities.create(db, hid, SecurityCreate(symbol="VTI"))
    with pytest.raises(ValueError, match="No account currently holds"):
        trades.create(
            db,
            hid,
            TradeIn(
                account_id=None,
                symbol="VTI",
                traded_on=date(2026, 2, 1),
                type=TradeType.split,
                split_ratio=Decimal("2"),
            ),
        )


def test_update_trade_revalidates_replay(db):
    hid = _household(db)
    acct = _account(db, hid)
    [buy] = trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 1, 1),
            type=TradeType.buy,
            quantity=Decimal("10"),
            price_per_unit=Decimal("10"),
        ),
    )
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 1, 5),
            type=TradeType.sell,
            quantity=Decimal("10"),
            price_per_unit=Decimal("15"),
        ),
    )
    # Shrinking the original buy now makes the sell exceed units held.
    with pytest.raises(portfolio.InsufficientUnitsError):
        trades.update(db, hid, buy.id, TradeUpdate(quantity=Decimal("5")))


def test_delete_trade_revalidates_replay(db):
    hid = _household(db)
    acct = _account(db, hid)
    [buy] = trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 1, 1),
            type=TradeType.buy,
            quantity=Decimal("10"),
            price_per_unit=Decimal("10"),
        ),
    )
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 1, 5),
            type=TradeType.sell,
            quantity=Decimal("10"),
            price_per_unit=Decimal("15"),
        ),
    )
    with pytest.raises(portfolio.InsufficientUnitsError):
        trades.delete(db, hid, buy.id)
    # nothing was removed
    rows, total = trades.list_for(db, hid)
    assert total == 2


def test_list_filters_by_security_and_account_and_date(db):
    hid = _household(db)
    acct1 = _account(db, hid, "A")
    acct2 = _account(db, hid, "B")
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct1.id,
            symbol="VTI",
            traded_on=date(2026, 1, 1),
            type=TradeType.buy,
            quantity=Decimal("1"),
            price_per_unit=Decimal("1"),
        ),
    )
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct2.id,
            symbol="BND",
            traded_on=date(2026, 6, 1),
            type=TradeType.buy,
            quantity=Decimal("1"),
            price_per_unit=Decimal("1"),
        ),
    )
    rows, total = trades.list_for(db, hid, account_id=acct1.id)
    assert total == 1
    rows, total = trades.list_for(db, hid, since=date(2026, 5, 1))
    assert total == 1


def test_delete_missing_trade_returns_false(db):
    hid = _household(db)
    assert trades.delete(db, hid, uuid.uuid4()) is False


# --- securities.py ------------------------------------------------------------------


def test_security_delete_blocked_when_trades_reference_it(db):
    hid = _household(db)
    acct = _account(db, hid)
    trades.create(
        db,
        hid,
        TradeIn(
            account_id=acct.id,
            symbol="VTI",
            traded_on=date(2026, 1, 1),
            type=TradeType.buy,
            quantity=Decimal("1"),
            price_per_unit=Decimal("1"),
        ),
    )
    sec = securities.get_by_symbol(db, hid, "VTI")
    with pytest.raises(securities.SecurityInUseError):
        securities.delete(db, hid, sec.id)


def test_security_delete_succeeds_with_no_trades(db):
    hid = _household(db)
    sec = securities.create(db, hid, SecurityCreate(symbol="VTI"))
    assert securities.delete(db, hid, sec.id) is True
    assert securities.get(db, hid, sec.id) is None


def test_securities_isolated_by_household(db):
    hid1 = _household(db)
    hid2 = _household(db)
    sec = securities.create(db, hid1, SecurityCreate(symbol="VTI"))
    assert securities.get(db, hid2, sec.id) is None
    assert securities.list_for(db, hid2) == []
