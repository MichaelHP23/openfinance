from app.models.household import Household
from app.schemas.account import AccountCreate
from app.services import accounts


def _household(db) -> Household:
    h = Household(name="Test Household")
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def test_accounts_isolated_by_household(db):
    h1, h2 = _household(db).id, _household(db).id
    a = accounts.create(db, h1, AccountCreate(type="checking", name="H1"))
    accounts.create(db, h2, AccountCreate(type="checking", name="H2"))

    assert {x.name for x in accounts.list_for(db, h1)} == {"H1"}
    assert accounts.get(db, h2, a.id) is None  # cannot read across household
    assert accounts.get(db, h1, a.id) is not None
