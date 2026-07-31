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


from datetime import UTC, datetime
from decimal import Decimal

from app.models.category_rule import CategoryRule, MatchType
from app.models.transaction import Transaction
from app.services.categorization import (
    BadPattern,
    compile_pattern,
    pick_category,
    rule_matches,
)

GROCERIES = system_category_id("Food & Drink/Groceries")
COFFEE = system_category_id("Food & Drink/Coffee")


def _txn(merchant: str, amount: str = "-42.00", account_id=None) -> Transaction:
    return Transaction(
        household_id=uuid.uuid4(),
        account_id=account_id or uuid.uuid4(),
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal(amount),
        currency="USD",
        merchant_raw=merchant,
    )


def _rule(**kw) -> CategoryRule:
    base = {
        "household_id": uuid.uuid4(),
        "match_type": MatchType.merchant_contains,
        "pattern": "whole foods",
        "category_id": GROCERIES,
        "priority": 100,
    }
    base.update(kw)
    return CategoryRule(**base)


def test_contains_matches_through_normalization():
    # merchant_key strips the "TST* " prefix, the store number, and the case.
    assert rule_matches(_rule(), _txn("TST* WHOLE FOODS #4471"))


def test_contains_does_not_match_unrelated_merchant():
    assert not rule_matches(_rule(), _txn("SHELL OIL"))


def test_exact_requires_the_whole_normalized_name():
    r = _rule(match_type=MatchType.merchant_exact, pattern="whole foods")
    assert rule_matches(r, _txn("WHOLE FOODS #4471"))
    assert not rule_matches(r, _txn("WHOLE FOODS MARKET"))


def test_regex_matches_normalized_name():
    r = _rule(match_type=MatchType.merchant_regex, pattern=r"^(whole foods|trader joe)")
    assert rule_matches(r, _txn("TRADER JOE S #22"))


def test_amount_band_bounds_the_match():
    r = _rule(min_amount=Decimal("-100.00"), max_amount=Decimal("-50.00"))
    assert rule_matches(r, _txn("WHOLE FOODS", "-75.00"))
    assert not rule_matches(r, _txn("WHOLE FOODS", "-20.00"))
    assert not rule_matches(r, _txn("WHOLE FOODS", "-150.00"))


def test_account_condition_bounds_the_match():
    account = uuid.uuid4()
    r = _rule(account_id=account)
    assert rule_matches(r, _txn("WHOLE FOODS", account_id=account))
    assert not rule_matches(r, _txn("WHOLE FOODS", account_id=uuid.uuid4()))


def test_first_rule_in_order_wins():
    specific = _rule(pattern="whole foods", category_id=COFFEE, priority=10)
    general = _rule(pattern="whole", category_id=GROCERIES, priority=50)
    assert pick_category([specific, general], _txn("WHOLE FOODS")) == COFFEE
    assert pick_category([general, specific], _txn("WHOLE FOODS")) == GROCERIES


def test_no_rule_matches_returns_none():
    assert pick_category([_rule()], _txn("SHELL OIL")) is None


def test_bad_regex_is_rejected_not_raised_at_match_time():
    try:
        compile_pattern(MatchType.merchant_regex, "(unclosed")
    except BadPattern:
        pass
    else:
        raise AssertionError("expected BadPattern")


def test_overlong_pattern_is_rejected():
    try:
        compile_pattern(MatchType.merchant_contains, "x" * 201)
    except BadPattern:
        pass
    else:
        raise AssertionError("expected BadPattern")


def test_a_rule_with_a_broken_pattern_never_matches():
    # Belt and braces: validation happens at write time, but a row that predates a
    # validation change must not take down categorization for every other rule.
    r = _rule(match_type=MatchType.merchant_regex, pattern="(unclosed")
    assert not rule_matches(r, _txn("ANYTHING"))
