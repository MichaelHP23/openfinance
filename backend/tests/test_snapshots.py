import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.household import Household
from app.schemas.account import AccountCreate
from app.services import accounts as accounts_service
from app.services import snapshots


def _household(db) -> uuid.UUID:
    h = Household(name="Snapshot Household")
    db.add(h)
    db.commit()
    return h.id


def _accounts(db, hid):
    accounts_service.create(
        db, hid, AccountCreate(type="checking", name="Checking", balance=Decimal(1000))
    )
    accounts_service.create(
        db, hid, AccountCreate(type="credit_card", name="Card", balance=Decimal(250))
    )


def test_capture_writes_one_row_per_account(db):
    hid = _household(db)
    _accounts(db, hid)
    assert snapshots.capture(db, hid) == 2


def test_capture_twice_in_a_day_does_not_duplicate(db):
    hid = _household(db)
    _accounts(db, hid)
    snapshots.capture(db, hid)
    assert snapshots.capture(db, hid) == 0
    assert len(snapshots.net_worth_series(db, hid)) == 1


def test_recapturing_a_day_records_the_newer_balance(db):
    hid = _household(db)
    _accounts(db, hid)
    snapshots.capture(db, hid)

    checking = next(a for a in accounts_service.list_for(db, hid) if a.name == "Checking")
    checking.balance = Decimal(1500)
    db.commit()
    snapshots.capture(db, hid)

    series = snapshots.net_worth_series(db, hid)
    assert len(series) == 1
    assert series[0].net == Decimal(1250)  # 1500 assets - 250 debt


def test_net_worth_subtracts_liabilities(db):
    hid = _household(db)
    _accounts(db, hid)
    snapshots.capture(db, hid)

    point = snapshots.net_worth_series(db, hid)[0]
    assert point.assets == Decimal(1000)
    assert point.debts == Decimal(250)
    assert point.net == Decimal(750)


def test_series_is_ordered_oldest_first_and_windowed(db):
    hid = _household(db)
    _accounts(db, hid)
    today = datetime.now(UTC).date()
    for offset in (100, 10, 3, 0):
        snapshots.capture(db, hid, on=today - timedelta(days=offset))

    series = snapshots.net_worth_series(db, hid, days=90)
    assert [p.on for p in series] == sorted(p.on for p in series)
    assert len(series) == 3  # the 100-day-old point falls outside the window


def test_capture_with_no_accounts_is_a_no_op(db):
    assert snapshots.capture(db, _household(db)) == 0


def test_snapshots_do_not_leak_across_households(db):
    mine, theirs = _household(db), _household(db)
    _accounts(db, mine)
    snapshots.capture(db, mine)
    assert snapshots.net_worth_series(db, theirs) == []


def test_series_can_be_narrowed_to_investment_accounts(db):
    from app.models.account import AccountType

    hid = _household(db)
    accounts_service.create(
        db, hid, AccountCreate(type="checking", name="Checking", balance=Decimal(400))
    )
    accounts_service.create(
        db, hid, AccountCreate(type="investment", name="Brokerage", balance=Decimal(2500))
    )
    snapshots.capture(db, hid)

    everything = snapshots.net_worth_series(db, hid)
    brokerage_only = snapshots.net_worth_series(db, hid, types={AccountType.investment})

    assert everything[0].net == Decimal(2900)
    assert brokerage_only[0].net == Decimal(2500)
