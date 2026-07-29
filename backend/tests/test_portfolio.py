import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.security import Security
from app.models.security_price import SecurityPrice
from app.models.trade import Trade, TradeType
from app.services import portfolio


def _household(db) -> uuid.UUID:
    h = Household(name="Portfolio Household")
    db.add(h)
    db.commit()
    return h.id


def _account(db, hid, name="Brokerage") -> Account:
    a = Account(household_id=hid, type=AccountType.investment, name=name, balance=Decimal(0))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _security(db, hid, symbol="VTI") -> Security:
    s = Security(household_id=hid, symbol=symbol, currency="USD")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _trade(db, hid, account, security, **kwargs) -> Trade:
    defaults = dict(
        household_id=hid,
        account_id=account.id,
        security_id=security.id,
        traded_on=date(2026, 1, 1),
        type=TradeType.buy,
        quantity=Decimal(0),
        price_per_unit=Decimal(0),
        fees=Decimal(0),
        currency="USD",
    )
    defaults.update(kwargs)
    t = Trade(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_buy_avg_cost_includes_fees(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db,
        hid,
        acct,
        sec,
        type=TradeType.buy,
        quantity=Decimal("10"),
        price_per_unit=Decimal("100"),
        fees=Decimal("5"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.units == Decimal("10")
    assert pos.cost_base == Decimal("1005")
    assert pos.avg_cost == Decimal("100.5")


def test_buy_buy_weighted_average_not_arithmetic_mean(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("30"), price_per_unit=Decimal("120")
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    # (10*100 + 30*120) / 40 = 115, not (100+120)/2 = 110
    assert pos.units == Decimal("40")
    assert pos.cost_base == Decimal("4600")
    assert pos.avg_cost == Decimal("115")


def test_sell_realized_gain_uses_average_cost_and_fees_reduce_proceeds(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.sell,
        quantity=Decimal("4"),
        price_per_unit=Decimal("150"),
        fees=Decimal("2"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    # avg cost 100, basis_sold = 400, proceeds = 4*150-2=598, realized=198
    assert pos.realized == Decimal("198")
    assert pos.units == Decimal("6")
    assert pos.cost_base == Decimal("600")


def test_sell_everything_zeroes_units_and_cost_base_exactly(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db,
        hid,
        acct,
        sec,
        type=TradeType.buy,
        quantity=Decimal("3"),
        price_per_unit=Decimal("33.333333"),
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.sell,
        quantity=Decimal("3"),
        price_per_unit=Decimal("50"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.units == Decimal("0")
    assert pos.cost_base == Decimal("0")


def test_sell_more_than_held_raises(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("5"), price_per_unit=Decimal("10")
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.sell,
        quantity=Decimal("6"),
        price_per_unit=Decimal("10"),
    )
    with pytest.raises(portfolio.InsufficientUnitsError):
        portfolio.positions(db, hid)


def test_two_for_one_split_doubles_units_keeps_cost_base_halves_avg_cost(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.split,
        split_ratio=Decimal("2"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.units == Decimal("20")
    assert pos.cost_base == Decimal("1000")
    assert pos.avg_cost == Decimal("50")


def test_reverse_split_halves_units(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.split,
        split_ratio=Decimal("0.5"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.units == Decimal("5")
    assert pos.cost_base == Decimal("1000")


def test_split_applies_per_account_not_globally(db):
    hid = _household(db)
    acct1 = _account(db, hid, "Roth")
    acct2 = _account(db, hid, "Taxable")
    sec = _security(db, hid)
    _trade(
        db,
        hid,
        acct1,
        sec,
        type=TradeType.buy,
        quantity=Decimal("10"),
        price_per_unit=Decimal("100"),
    )
    _trade(
        db,
        hid,
        acct2,
        sec,
        type=TradeType.buy,
        quantity=Decimal("5"),
        price_per_unit=Decimal("100"),
    )
    _trade(
        db,
        hid,
        acct1,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.split,
        split_ratio=Decimal("2"),
    )
    pos = portfolio.positions(db, hid)
    assert pos[(sec.id, acct1.id)].units == Decimal("20")
    assert pos[(sec.id, acct2.id)].units == Decimal("5")  # untouched


def test_dividend_does_not_touch_position_but_raises_dividend_total(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.dividend,
        quantity=Decimal("10"),
        price_per_unit=Decimal("0.50"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.units == Decimal("10")
    assert pos.cost_base == Decimal("1000")
    assert pos.dividends == Decimal("5.00")


def test_dividend_with_only_total_amount_and_zero_quantity(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db,
        hid,
        acct,
        sec,
        type=TradeType.dividend,
        quantity=Decimal("0"),
        price_per_unit=Decimal("12.34"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.dividends == Decimal("12.34")


def test_same_day_trades_apply_in_created_at_order(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    # A same-day buy then sell must apply buy first so the sell doesn't reject.
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("5"), price_per_unit=Decimal("10")
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        type=TradeType.sell,
        quantity=Decimal("5"),
        price_per_unit=Decimal("12"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.units == Decimal("0")
    assert pos.realized == Decimal("10")


def test_decimal_precision_no_float_slop(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db,
        hid,
        acct,
        sec,
        type=TradeType.buy,
        quantity=Decimal("0.1"),
        price_per_unit=Decimal("1"),
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 1, 2),
        type=TradeType.buy,
        quantity=Decimal("0.2"),
        price_per_unit=Decimal("1"),
    )
    pos = portfolio.positions(db, hid)[(sec.id, acct.id)]
    assert pos.units == Decimal("0.3")
    assert pos.cost_base == Decimal("0.3")


def test_positions_scoped_by_household(db):
    hid1 = _household(db)
    hid2 = _household(db)
    acct1 = _account(db, hid1)
    sec1 = _security(db, hid1)
    _trade(
        db, hid1, acct1, sec1, type=TradeType.buy, quantity=Decimal("1"), price_per_unit=Decimal("1")
    )
    assert portfolio.positions(db, hid2) == {}


def test_latest_price_picks_most_recent_on_or_before(db):
    hid = _household(db)
    sec = _security(db, hid)
    db.add(SecurityPrice(security_id=sec.id, priced_on=date(2026, 1, 1), close=Decimal("10")))
    db.add(SecurityPrice(security_id=sec.id, priced_on=date(2026, 1, 10), close=Decimal("12")))
    db.commit()
    p = portfolio.latest_price(db, sec.id, as_of=date(2026, 1, 15))
    assert p is not None and p.close == Decimal("12")
    p_before = portfolio.latest_price(db, sec.id, as_of=date(2026, 1, 5))
    assert p_before is not None and p_before.close == Decimal("10")
    p_none = portfolio.latest_price(db, sec.id, as_of=date(2025, 12, 1))
    assert p_none is None


def test_holdings_reports_market_value_and_unrealized(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    db.add(SecurityPrice(security_id=sec.id, priced_on=date(2026, 1, 15), close=Decimal("120")))
    db.commit()
    result = portfolio.holdings(db, hid, as_of=date(2026, 1, 20))
    assert len(result.holdings) == 1
    h = result.holdings[0]
    assert h.units == Decimal("10")
    assert h.cost_base == Decimal("1000")
    assert h.price == Decimal("120")
    assert h.market_value == Decimal("1200")
    assert h.unrealized == Decimal("200")
    assert h.unrealized_pct == Decimal("20")  # 200/1000 * 100
    assert h.priced_on == date(2026, 1, 15)
    assert result.priced_through == date(2026, 1, 15)


def test_holdings_unpriced_security_reports_none_market_value(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    result = portfolio.holdings(db, hid)
    h = result.holdings[0]
    assert h.price is None
    assert h.market_value is None
    assert h.unrealized is None
    assert result.priced_through is None


def test_holdings_excludes_fully_sold_positions(db):
    hid = _household(db)
    acct = _account(db, hid)
    sec = _security(db, hid)
    _trade(
        db, hid, acct, sec, type=TradeType.buy, quantity=Decimal("10"), price_per_unit=Decimal("100")
    )
    _trade(
        db,
        hid,
        acct,
        sec,
        traded_on=date(2026, 2, 1),
        type=TradeType.sell,
        quantity=Decimal("10"),
        price_per_unit=Decimal("110"),
    )
    result = portfolio.holdings(db, hid)
    assert result.holdings == []
