from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.security import Security
from app.models.trade import Trade, TradeType
from app.models.transaction import Transaction
from app.services import tax
from app.services.categories import ensure_system_categories, system_category_id

app.state.limiter.enabled = False


@pytest.fixture
def household(db):
    row = Household(name="Tax Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(household_id=household.id, type=AccountType.investment, name="Brokerage", currency="USD")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def security(db, household):
    row = Security(household_id=household.id, symbol="VTI", name="Vanguard Total Stock", currency="USD")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def _trade(household, account, security, **kw):
    base = {
        "household_id": household.id, "account_id": account.id, "security_id": security.id,
        "fees": Decimal(0), "currency": "USD",
    }
    base.update(kw)
    return Trade(**base)


def test_fifo_across_partial_sells_and_multiple_lots(db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2025, 6, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(20)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(15), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    result = tax.realized_gains(db, household.id, 2026)

    assert len(result.gains) == 2
    lot_a, lot_b = result.gains
    # Lot A: bought 2024-01-01, fully consumed by the sale — held > 365 days, long-term.
    assert lot_a.opened_on == date(2024, 1, 1)
    assert lot_a.quantity == Decimal(10)
    assert lot_a.cost_basis == Decimal(100)
    assert lot_a.proceeds == Decimal(300)
    assert lot_a.gain == Decimal(200)
    assert lot_a.term == "long"
    # Lot B: bought 2025-06-01, partially consumed (5 of 10 units) — under 365 days, short-term.
    assert lot_b.opened_on == date(2025, 6, 1)
    assert lot_b.quantity == Decimal(5)
    assert lot_b.cost_basis == Decimal(100)
    assert lot_b.proceeds == Decimal(150)
    assert lot_b.gain == Decimal(50)
    assert lot_b.term == "short"

    assert result.short_term_gain == Decimal(50)
    assert result.long_term_gain == Decimal(200)
    assert result.total_gain == Decimal(250)


def test_realized_gains_for_a_year_with_no_sells(db, household, account, security):
    db.add(
        _trade(household, account, security, traded_on=date(2026, 3, 1), type=TradeType.buy,
               quantity=Decimal(10), price_per_unit=Decimal(10))
    )
    db.commit()

    result = tax.realized_gains(db, household.id, 2026)

    assert result.gains == []
    assert result.short_term_gain == Decimal(0)
    assert result.long_term_gain == Decimal(0)
    assert result.total_gain == Decimal(0)


def test_a_split_scales_the_open_lot_without_changing_its_holding_period(db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2025, 1, 1), type=TradeType.split,
                   split_ratio=Decimal(2)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(20), price_per_unit=Decimal(8)),
        ]
    )
    db.commit()

    result = tax.realized_gains(db, household.id, 2026)

    assert len(result.gains) == 1
    gain = result.gains[0]
    # 10 units @ $10 = $100 total cost; the split doubles units and halves cost/unit,
    # so total cost basis is unchanged at $100 for all 20 post-split units.
    assert gain.cost_basis == Decimal(100)
    assert gain.proceeds == Decimal(160)
    assert gain.gain == Decimal(60)
    # The split doesn't restart the clock — opened_on is still the original buy.
    assert gain.opened_on == date(2024, 1, 1)
    assert gain.term == "long"


def test_realized_gains_endpoint(client, db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(10), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    res = client.get("/tax/realized-gains?year=2026")
    assert res.status_code == 200
    body = res.json()
    assert body["total_gain"] == "200.00"
    assert body["gains"][0]["symbol"] == "VTI"


def test_income_summary_reads_dividends_and_interest_from_categorized_transactions(db, household, account):
    ensure_system_categories(db)
    dividends = system_category_id("Income/Dividends")
    interest = system_category_id("Income/Interest")
    db.add_all(
        [
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2026, 3, 1, tzinfo=UTC), amount=Decimal("120.00"),
                        currency="USD", merchant_raw="VTI DIV", category_id=dividends),
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2026, 4, 1, tzinfo=UTC), amount=Decimal("5.00"),
                        currency="USD", merchant_raw="BANK INTEREST", category_id=interest),
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2025, 12, 1, tzinfo=UTC), amount=Decimal("999.00"),
                        currency="USD", merchant_raw="LAST YEAR DIV", category_id=dividends),
        ]
    )
    db.commit()

    summary = tax.income_summary(db, household.id, 2026)

    assert summary.dividends == Decimal("120.00")
    assert summary.interest == Decimal("5.00")
    assert summary.total == Decimal("125.00")


def test_income_summary_ignores_trade_log_dividends(db, household, account, security):
    """Dividends recorded as a Trade row are a different feature's data and are not
    double-counted here — see the plan's recorded deviation on why."""
    db.add(
        _trade(household, account, security, traded_on=date(2026, 3, 1), type=TradeType.dividend,
               quantity=Decimal(0), price_per_unit=Decimal("50.00"))
    )
    db.commit()

    assert tax.income_summary(db, household.id, 2026).total == Decimal(0)


def test_export_csv_discloses_wash_sales_are_not_handled(db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(10), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    csv_text = tax.export_csv(db, household.id, 2026)

    assert "wash sale" in csv_text.lower()
    assert "advice" not in csv_text.lower()
    assert "VTI" in csv_text
    assert "Short-term total" in csv_text
    assert "Long-term total" in csv_text


def test_export_endpoint_returns_csv(client, db, household, account, security):
    db.add_all(
        [
            _trade(household, account, security, traded_on=date(2024, 1, 1), type=TradeType.buy,
                   quantity=Decimal(10), price_per_unit=Decimal(10)),
            _trade(household, account, security, traded_on=date(2026, 1, 1), type=TradeType.sell,
                   quantity=Decimal(10), price_per_unit=Decimal(30)),
        ]
    )
    db.commit()

    res = client.get("/tax/export?year=2026")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "wash sale" in res.text.lower()
