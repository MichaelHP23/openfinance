import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.household import Household
from app.schemas.account import AccountCreate
from app.schemas.transaction import TxnCreate
from app.services import accounts as accounts_service
from app.services import investments
from app.services import transactions as txn_service


def _household(db) -> uuid.UUID:
    h = Household(name="Investments Household")
    db.add(h)
    db.commit()
    return h.id


def _seed(db, hid):
    brokerage = accounts_service.create(
        db, hid, AccountCreate(type="investment", name="ROTH IRA", balance=Decimal(6000))
    )
    taxable = accounts_service.create(
        db, hid, AccountCreate(type="investment", name="Individual", balance=Decimal(2000))
    )
    accounts_service.create(
        db, hid, AccountCreate(type="checking", name="Checking", balance=Decimal(500))
    )
    now = datetime.now(UTC)
    for account, merchant, amount, days in [
        (brokerage, "DIVIDEND RECEIVED VTSAX", "42.10", 20),
        (brokerage, "DIVIDEND RECEIVED VTSAX", "39.80", 110),
        (taxable, "Interest Paid", "3.25", 15),
        (taxable, "ACH CONTRIBUTION", "500.00", 12),
        (taxable, "Stock purchase", "-450.00", 11),
    ]:
        txn_service.create(
            db,
            hid,
            TxnCreate(
                account_id=account.id,
                posted_at=now - timedelta(days=days),
                amount=Decimal(amount),
                merchant_raw=merchant,
            ),
        )
    return brokerage, taxable


def test_no_investment_accounts_gives_an_empty_summary(db):
    out = investments.summary(db, _household(db))
    assert out.total_value == 0.0
    assert out.account_count == 0
    assert out.has_income_data is False


def test_total_value_counts_only_investment_accounts(db):
    hid = _household(db)
    _seed(db, hid)
    out = investments.summary(db, hid)
    assert out.total_value == 8000.0  # the checking account is excluded
    assert out.account_count == 2


def test_dividends_and_interest_are_recognised_as_income(db):
    hid = _household(db)
    _seed(db, hid)
    out = investments.summary(db, hid)
    assert out.income_all_time == 85.15  # 42.10 + 39.80 + 3.25
    assert out.has_income_data is True


def test_contributions_are_separated_from_income(db):
    hid = _household(db)
    _seed(db, hid)
    out = investments.summary(db, hid)
    assert out.contributions_ytd == 500.0
    assert 500.0 not in [row["amount"] for row in out.recent_income]


def test_purchases_do_not_count_as_income_or_contributions(db):
    hid = _household(db)
    _seed(db, hid)
    out = investments.summary(db, hid)
    assert all(row["amount"] > 0 for row in out.recent_income)


def test_accounts_carry_their_share_of_the_portfolio(db):
    hid = _household(db)
    _seed(db, hid)
    shares = {a["name"]: a["share"] for a in investments.summary(db, hid).accounts}
    assert shares["ROTH IRA"] == 75.0
    assert shares["Individual"] == 25.0


def test_per_account_income_is_attributed_correctly(db):
    hid = _household(db)
    _seed(db, hid)
    income = {a["name"]: a["income"] for a in investments.summary(db, hid).accounts}
    assert income["ROTH IRA"] == 81.9
    assert income["Individual"] == 3.25


def test_income_is_bucketed_by_month(db):
    hid = _household(db)
    _seed(db, hid)
    months = investments.summary(db, hid).income_by_month
    assert len(months) >= 2
    assert months == sorted(months, key=lambda m: m.month)


def test_income_detection_matches_common_phrasings():
    for merchant in [
        "DIVIDEND RECEIVED",
        "Qualified Div",
        "Interest Paid",
        "CAPITAL GAIN DISTRIBUTION",
        "Div Reinvestment",
    ]:
        assert investments.is_income(merchant) is True
    for merchant in ["Stock purchase", "ACH CONTRIBUTION", "Amazon"]:
        assert investments.is_income(merchant) is False


def test_another_household_sees_nothing(db):
    hid = _household(db)
    _seed(db, hid)
    assert investments.summary(db, uuid.uuid4()).total_value == 0.0
