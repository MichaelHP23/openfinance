from app.models.household import Household
from app.schemas.account import AccountCreate
from app.services import accounts, csv_import, transactions

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


def test_import_categorizes_new_rows(db):
    from sqlalchemy import select

    from app.models.category_rule import CategoryRule, MatchType
    from app.models.transaction import Transaction
    from app.services.categories import ensure_system_categories, system_category_id

    hid = _household(db).id
    acct = accounts.create(db, hid, AccountCreate(type="checking", name="Main"))

    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    db.add(
        CategoryRule(
            household_id=hid,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=groceries,
            priority=100,
        )
    )
    db.commit()

    raw = "date,amount,merchant\n2026-07-01,-42.00,WHOLE FOODS #4471\n"
    result = csv_import.import_csv(db, hid, acct.id, raw)

    assert result.imported == 1
    assert result.categorized == 1

    txn = db.scalar(select(Transaction).where(Transaction.household_id == hid))
    assert txn.category_id == groceries
