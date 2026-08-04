from datetime import date
from decimal import Decimal

from app.models.household import Household
from app.schemas.account import AccountCreate
from app.schemas.budget import BudgetItemIn  # noqa: F401  (kept import-adjacent; unused directly)
from app.schemas.category import CategoryCreate, RuleCreate, RuleUpdate
from app.services import accounts, budgets, categories, categorization
from app.services.categories import ensure_system_categories, system_category_id


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


def test_category_rules_isolated_by_household(db):
    h1, h2 = _household(db).id, _household(db).id
    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    rule = categorization.create_rule(
        db, h1, RuleCreate(pattern="whole foods", category_id=groceries)
    )
    categorization.create_rule(
        db, h2, RuleCreate(pattern="blue bottle", category_id=groceries)
    )

    assert {r.pattern for r in categorization.rules_for(db, h1)} == {"whole foods"}
    assert categorization.get_rule(db, h2, rule.id) is None
    assert categorization.update_rule(db, h2, rule.id, RuleUpdate(priority=1)) is None
    assert categorization.delete_rule(db, h2, rule.id) is False
    assert categorization.get_rule(db, h1, rule.id) is not None


def test_custom_categories_isolated_but_system_ones_are_shared(db):
    h1, h2 = _household(db).id, _household(db).id
    ensure_system_categories(db)
    mine = categories.create(db, h1, CategoryCreate(name="Boat Fuel"))

    assert categories.get(db, h2, mine.id) is None
    assert categories.get(db, h1, mine.id) is not None
    # System rows carry no household_id, so both sides see the same taxonomy.
    shared = system_category_id("Food & Drink/Groceries")
    assert categories.get(db, h1, shared) is not None
    assert categories.get(db, h2, shared) is not None
    # ...and a rule in one household cannot borrow the other's custom category.
    try:
        categorization.create_rule(
            db, h2, RuleCreate(pattern="boats", category_id=mine.id)
        )
    except categorization.UnknownCategory:
        pass
    else:
        raise AssertionError("expected UnknownCategory")


def test_budgets_isolated_by_household(db):
    h1, h2 = _household(db).id, _household(db).id
    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    budgets.upsert(
        db, h1, date(2026, 7, 1), [budgets.BudgetItem(groceries, Decimal("300.00"))]
    )

    assert len(budgets.list_budgets(db, h1, date(2026, 7, 1))) == 1
    assert len(budgets.list_budgets(db, h2, date(2026, 7, 1))) == 0
    h2_status = next(
        r for r in budgets.status(db, h2, date(2026, 7, 1)) if r.category_id == groceries
    )
    assert h2_status.budgeted == Decimal("0")
