import uuid

from app.models.category import Category
from app.services.categories import (
    TAXONOMY,
    ensure_system_categories,
    system_category_id,
)


def test_seed_creates_groups_and_leaves(db):
    inserted = ensure_system_categories(db)
    expected = len(TAXONOMY) + sum(len(v) for v in TAXONOMY.values())
    assert inserted == expected

    groceries = db.get(Category, system_category_id("Food & Drink/Groceries"))
    assert groceries is not None
    assert groceries.name == "Groceries"
    assert groceries.household_id is None
    assert groceries.parent_id == system_category_id("Food & Drink")


def test_seed_is_idempotent(db):
    ensure_system_categories(db)
    assert ensure_system_categories(db) == 0


def test_system_category_ids_are_stable():
    assert system_category_id("Food & Drink/Groceries") == system_category_id(
        "Food & Drink/Groceries"
    )
    assert isinstance(system_category_id("Transfers"), uuid.UUID)
