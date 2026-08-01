"""The system category taxonomy, and CRUD over household-owned categories.

The taxonomy lives here rather than in the migration because tests build their schema
with `Base.metadata.create_all`, never with Alembic — so a seed that only exists inside
a migration would be absent in every test. The migration imports this module.

System category ids are uuid5 over the category's path, so they are identical on every
install. That makes the seeder idempotent without a unique constraint, and it means a
rule exported from one install still points at a real category on another.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.category_rule import CategoryRule
from app.models.transaction import Transaction
from app.schemas.category import CategoryCreate, CategoryUpdate

# uuid5 needs a fixed namespace. Any constant UUID does; this one was generated once.
_NAMESPACE = uuid.UUID("6f2a1c14-9a5f-4b3e-8d21-0c7f5a9e4b10")

TAXONOMY: dict[str, list[str]] = {
    "Income": ["Paycheck", "Bonus", "Interest", "Dividends", "Refunds", "Other Income"],
    "Housing": [
        "Rent",
        "Mortgage",
        "Property Tax",
        "Home Insurance",
        "Home Maintenance",
        "Furnishings",
    ],
    "Bills & Utilities": [
        "Electric",
        "Gas",
        "Water",
        "Internet",
        "Mobile Phone",
        "Streaming",
        "Other Bills",
    ],
    "Transport": [
        "Gas & Fuel",
        "Public Transit",
        "Rideshare",
        "Parking",
        "Car Payment",
        "Car Insurance",
        "Car Maintenance",
    ],
    "Food & Drink": ["Groceries", "Restaurants", "Coffee", "Bars", "Delivery"],
    "Shopping": ["Clothing", "Electronics", "Household Goods", "Gifts", "Hobbies"],
    "Health": ["Doctor", "Pharmacy", "Dental", "Vision", "Health Insurance", "Fitness"],
    "Entertainment": ["Movies & Music", "Games", "Events", "Books"],
    "Travel": ["Flights", "Hotels", "Rental Car", "Vacation Other"],
    "Personal": ["Haircut & Beauty", "Childcare", "Education", "Pets", "Subscriptions"],
    "Financial": ["Bank Fees", "Interest Charged", "Taxes", "Investments", "Charity"],
    "Transfers": ["Transfer", "Credit Card Payment", "Loan Payment"],
}


def system_category_id(path: str) -> uuid.UUID:
    """Stable id for a system category. `path` is "Group" or "Group/Leaf"."""
    return uuid.uuid5(_NAMESPACE, f"openfinance:category:{path}")


def ensure_system_categories(db: Session) -> int:
    """Insert any missing system category. Returns how many rows it added."""
    present = set(
        db.scalars(select(Category.id).where(Category.household_id.is_(None)))
    )
    added = 0
    for group, leaves in TAXONOMY.items():
        group_id = system_category_id(group)
        if group_id not in present:
            db.add(Category(id=group_id, household_id=None, name=group, parent_id=None))
            added += 1
        for leaf in leaves:
            leaf_id = system_category_id(f"{group}/{leaf}")
            if leaf_id not in present:
                db.add(
                    Category(
                        id=leaf_id, household_id=None, name=leaf, parent_id=group_id
                    )
                )
                added += 1
    db.commit()
    return added


class SystemCategoryImmutable(Exception):
    """System categories are shared by every install. They are read-only, always."""


class UnknownParent(Exception):
    """The requested parent does not exist, or belongs to another household."""


class CategoryInUse(Exception):
    """Something still points at this category, so deleting it would orphan rows."""


def list_for(db: Session, household_id: uuid.UUID) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .where(
                (Category.household_id == household_id)
                | (Category.household_id.is_(None))
            )
            .order_by(Category.parent_id.nulls_first(), Category.name)
        )
    )


def get(db: Session, household_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
    row = db.get(Category, category_id)
    if row is None:
        return None
    if row.household_id is not None and row.household_id != household_id:
        return None
    return row


def _check_parent(db: Session, household_id: uuid.UUID, parent_id: uuid.UUID | None) -> None:
    """A parent must be visible to this household, or the FK fails as a 500 instead."""
    if parent_id is not None and get(db, household_id, parent_id) is None:
        raise UnknownParent(str(parent_id))


def create(db: Session, household_id: uuid.UUID, data: CategoryCreate) -> Category:
    _check_parent(db, household_id, data.parent_id)
    row = Category(household_id=household_id, name=data.name, parent_id=data.parent_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update(
    db: Session, household_id: uuid.UUID, category_id: uuid.UUID, data: CategoryUpdate
) -> Category | None:
    row = get(db, household_id, category_id)
    if row is None:
        return None
    if row.household_id is None:
        raise SystemCategoryImmutable(str(category_id))
    fields = data.model_dump(exclude_unset=True)
    if "parent_id" in fields:
        if fields["parent_id"] == category_id:
            raise UnknownParent("a category cannot be its own parent")
        _check_parent(db, household_id, fields["parent_id"])
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, household_id: uuid.UUID, category_id: uuid.UUID) -> bool:
    row = get(db, household_id, category_id)
    if row is None:
        return False
    if row.household_id is None:
        raise SystemCategoryImmutable(str(category_id))
    # ponytail: refuse rather than cascade. Reassign-then-delete is the user's call to
    # make, not ours; add a `reassign_to` param if the UI ever wants one-click cleanup.
    if db.scalar(select(Category.id).where(Category.parent_id == category_id).limit(1)):
        raise CategoryInUse("category still has child categories")
    if db.scalar(
        select(Transaction.id).where(Transaction.category_id == category_id).limit(1)
    ):
        raise CategoryInUse("category is still assigned to transactions")
    # CategoryRule.category_id is ON DELETE CASCADE, so without this the rule disappears
    # with the category and the household is never told why matching stopped working.
    if db.scalar(
        select(CategoryRule.id).where(CategoryRule.category_id == category_id).limit(1)
    ):
        raise CategoryInUse("a rule still points at this category")
    db.delete(row)
    db.commit()
    return True
