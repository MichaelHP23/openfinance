from app.models.household import Household
from app.services import accounts, csv_import, transactions
from app.schemas.account import AccountCreate

CSV = "date,amount,merchant\n2026-01-01,-9.99,Starbucks\n2026-01-02,-4.50,Amazon\n"


def _household(db) -> Household:
    h = Household(name="Test Household")
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def test_import_creates_transactions(db):
    hid = _household(db).id
    acct = accounts.create(db, hid, AccountCreate(type="checking", name="Main"))
    res = csv_import.import_csv(db, hid, acct.id, CSV)
    assert res.imported == 2 and res.skipped == 0
    assert len(transactions.list_for(db, hid)) == 2


def test_reimport_is_deduped(db):
    hid = _household(db).id
    acct = accounts.create(db, hid, AccountCreate(type="checking", name="Main"))
    csv_import.import_csv(db, hid, acct.id, CSV)
    res = csv_import.import_csv(db, hid, acct.id, CSV)
    assert res.imported == 0 and res.skipped == 2
