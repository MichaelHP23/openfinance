from decimal import Decimal

from app.models.household import Household
from app.schemas.account import AccountCreate
from app.services import accounts


def _household(db) -> Household:
    h = Household(name="Test Household")
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def test_create_and_list(db):
    hid = _household(db).id
    accounts.create(db, hid, AccountCreate(type="checking", name="Main", balance=Decimal("100.50")))
    rows = accounts.list_for(db, hid)
    assert len(rows) == 1
    assert rows[0].balance == Decimal("100.5000")


def test_rejects_non_usd(db):
    import pytest

    hid = _household(db).id
    with pytest.raises(ValueError):
        accounts.create(db, hid, AccountCreate(type="cash", name="x", currency="EUR"))


def _real_household(db):
    """accounts.household_id is a real FK, so these tests need a real household row."""
    from app.models.household import Household

    household = Household(name="Accounts Household")
    db.add(household)
    db.commit()
    return household.id


def test_delete_removes_the_account_and_its_transactions(db):
    from datetime import UTC, datetime

    from app.schemas.transaction import TxnCreate
    from app.services import snapshots, transactions

    hid = _real_household(db)
    acct = accounts.create(db, hid, AccountCreate(type="checking", name="Doomed"))
    transactions.create(
        db,
        hid,
        TxnCreate(
            account_id=acct.id,
            posted_at=datetime.now(UTC),
            amount=Decimal(-1),
            merchant_raw="X",
        ),
    )

    assert accounts.delete(db, hid, acct.id) is True
    assert accounts.get(db, hid, acct.id) is None
    assert transactions.list_for(db, hid) == []
    assert snapshots.net_worth_series(db, hid) == []


def test_delete_refuses_another_households_account(db):
    import uuid as _uuid

    mine, theirs = _real_household(db), _uuid.uuid4()
    acct = accounts.create(db, mine, AccountCreate(type="checking", name="Mine"))

    assert accounts.delete(db, theirs, acct.id) is False
    assert accounts.get(db, mine, acct.id) is not None


def test_delete_missing_account_reports_false(db):
    import uuid as _uuid

    assert accounts.delete(db, _uuid.uuid4(), _uuid.uuid4()) is False
