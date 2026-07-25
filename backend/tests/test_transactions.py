from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.household import Household
from app.schemas.account import AccountCreate
from app.schemas.transaction import TxnCreate, TxnUpdate
from app.services import accounts, transactions


def _household(db) -> Household:
    h = Household(name="Test Household")
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def _acct(db, hid):
    return accounts.create(db, hid, AccountCreate(type="checking", name="Main"))


def test_create_list_filter(db):
    hid = _household(db).id
    acct = _acct(db, hid)
    transactions.create(
        db,
        hid,
        TxnCreate(
            account_id=acct.id,
            posted_at=datetime(2026, 1, 1, tzinfo=UTC),
            amount=Decimal("-9.99"),
            merchant_raw="Starbucks",
        ),
    )
    transactions.create(
        db,
        hid,
        TxnCreate(
            account_id=acct.id,
            posted_at=datetime(2026, 2, 1, tzinfo=UTC),
            amount=Decimal("-4.50"),
            merchant_raw="Amazon",
        ),
    )
    assert len(transactions.list_for(db, hid)) == 2
    assert len(transactions.list_for(db, hid, search="star")) == 1
    assert len(transactions.list_for(db, hid, since=datetime(2026, 1, 15, tzinfo=UTC))) == 1


def test_create_rejects_foreign_account(db):
    hid, other = _household(db).id, _household(db).id
    acct = _acct(db, other)
    with pytest.raises(transactions.AccountNotInHousehold):
        transactions.create(
            db,
            hid,
            TxnCreate(
                account_id=acct.id, posted_at=datetime.now(UTC), amount=Decimal(1), merchant_raw="x"
            ),
        )


def test_update_and_delete(db):
    hid = _household(db).id
    acct = _acct(db, hid)
    t = transactions.create(
        db,
        hid,
        TxnCreate(
            account_id=acct.id, posted_at=datetime.now(UTC), amount=Decimal(-1), merchant_raw="Cafe"
        ),
    )
    transactions.update(db, hid, t.id, TxnUpdate(notes="lunch", merchant_normalized="Cafe Inc"))
    assert transactions.get(db, hid, t.id).notes == "lunch"
    assert transactions.delete(db, hid, t.id) is True
    assert transactions.get(db, hid, t.id) is None


def test_txn_tenancy_isolation(db):
    h1, h2 = _household(db).id, _household(db).id
    acct = _acct(db, h1)
    t = transactions.create(
        db,
        h1,
        TxnCreate(
            account_id=acct.id, posted_at=datetime.now(UTC), amount=Decimal(-1), merchant_raw="X"
        ),
    )
    assert transactions.get(db, h2, t.id) is None
    assert transactions.list_for(db, h2) == []
