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
