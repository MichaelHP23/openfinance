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
from app.models.household import Household
from app.models.transaction import Transaction
from app.schemas.account import AccountCreate
from app.schemas.category import RuleCreate
from app.schemas.transaction import TxnCreate
from app.services import accounts, categorization, transactions
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


def test_pattern_that_normalizes_to_nothing_is_rejected():
    # Otherwise it stores fine and then matches every transaction: "" in name is True.
    for match_type in (MatchType.merchant_contains, MatchType.merchant_exact):
        try:
            compile_pattern(match_type, "#1234")
        except BadPattern:
            pass
        else:
            raise AssertionError(f"expected BadPattern for {match_type}")


def test_regex_pattern_keeps_its_metacharacters():
    compile_pattern(MatchType.merchant_regex, r"^whole ?foods.*")


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


def _household_and_account(db):
    household = Household(name="Categorization test household")
    db.add(household)
    db.commit()
    account = accounts.create(
        db, household.id, AccountCreate(type="checking", name="Categorization checking")
    )
    return household, account


def test_apply_sets_category_on_uncategorized_rows(db):
    household, account = _household_and_account(db)
    ensure_system_categories(db)
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=GROCERIES,
            priority=100,
        )
    )
    txns = [
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS #4471",
        ),
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 2, tzinfo=UTC),
            amount=Decimal("-9.00"),
            currency="USD",
            merchant_raw="SHELL OIL",
        ),
    ]
    db.add_all(txns)
    db.commit()

    assert categorization.apply_to(db, household.id, txns) == 1
    assert txns[0].category_id == GROCERIES
    assert txns[1].category_id is None


def test_apply_does_not_touch_a_transaction_from_another_household(db):
    household, _account = _household_and_account(db)
    other_household, other_account = _household_and_account(db)
    ensure_system_categories(db)
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=GROCERIES,
            priority=100,
        )
    )
    other_txn = Transaction(
        household_id=other_household.id,
        account_id=other_account.id,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal("-42.00"),
        currency="USD",
        merchant_raw="WHOLE FOODS",
    )
    db.add(other_txn)
    db.commit()

    assert categorization.apply_to(db, household.id, [other_txn]) == 0
    assert other_txn.category_id is None


def test_backfill_leaves_hand_set_categories_alone(db):
    household, account = _household_and_account(db)
    ensure_system_categories(db)
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=GROCERIES,
            priority=100,
        )
    )
    hand_set = Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal("-42.00"),
        currency="USD",
        merchant_raw="WHOLE FOODS",
        category_id=COFFEE,
    )
    db.add(hand_set)
    db.commit()

    assert categorization.backfill(db, household.id) == 0
    db.refresh(hand_set)
    assert hand_set.category_id == COFFEE


def test_backfill_can_overwrite_categories_when_requested(db):
    household, account = _household_and_account(db)
    ensure_system_categories(db)
    db.add(
        CategoryRule(
            household_id=household.id,
            match_type=MatchType.merchant_contains,
            pattern="whole foods",
            category_id=GROCERIES,
            priority=100,
        )
    )
    hand_set = Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        amount=Decimal("-42.00"),
        currency="USD",
        merchant_raw="WHOLE FOODS",
        category_id=COFFEE,
    )
    db.add(hand_set)
    db.commit()

    assert categorization.backfill(db, household.id, only_uncategorized=False) == 1
    db.refresh(hand_set)
    assert hand_set.category_id == GROCERIES


def test_uncategorized_rollup_groups_by_normalized_merchant(db):
    household, account = _household_and_account(db)
    db.add_all(
        [
            Transaction(
                household_id=household.id,
                account_id=account.id,
                posted_at=datetime(2026, 7, day, tzinfo=UTC),
                amount=Decimal("-10.00"),
                currency="USD",
                merchant_raw=raw,
            )
            for day, raw in [(1, "SHELL OIL #221"), (2, "SHELL OIL #907"), (3, "KROGER")]
        ]
    )
    db.commit()

    by_name = {
        row.merchant: row
        for row in categorization.uncategorized_merchants(db, household.id)
    }
    assert by_name["shell oil"].count == 2
    assert by_name["shell oil"].total == Decimal("-20.00")
    assert by_name["kroger"].count == 1


def test_a_hand_entered_transaction_is_categorized_too(db):
    """A rule the user wrote should hold however the row arrives, not only on import."""
    household, account = _household_and_account(db)
    ensure_system_categories(db)
    categorization.create_rule(
        db, household.id, RuleCreate(pattern="whole foods", category_id=GROCERIES)
    )

    txn = transactions.create(
        db,
        household.id,
        TxnCreate(
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS #4471",
        ),
    )
    assert txn.category_id == GROCERIES


def test_a_category_typed_in_by_hand_beats_the_rules(db):
    household, account = _household_and_account(db)
    ensure_system_categories(db)
    categorization.create_rule(
        db, household.id, RuleCreate(pattern="whole foods", category_id=GROCERIES)
    )

    txn = transactions.create(
        db,
        household.id,
        TxnCreate(
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="WHOLE FOODS #4471",
            category_id=COFFEE,
        ),
    )
    assert txn.category_id == COFFEE


def test_a_regex_that_backtracks_forever_is_rejected():
    # "(a+)+b" against thirty a's never returns. `re` has no step budget and this runs
    # inline on every arriving transaction, so the rule must not be storable at all.
    for pattern in ("(a+)+b", "(ab*){2,}", "(x+)*y"):
        try:
            compile_pattern(MatchType.merchant_regex, pattern)
        except BadPattern:
            pass
        else:
            raise AssertionError(f"expected BadPattern for {pattern}")


def test_ordinary_regexes_still_pass():
    compile_pattern(MatchType.merchant_regex, r"^(whole foods|trader joe)")
    compile_pattern(MatchType.merchant_regex, r"^whole ?foods.*")


def test_a_merchant_that_normalizes_to_nothing_still_shows_as_uncategorized(db):
    # merchant_key("123456") is "". Dropping the row would hide it from the only screen
    # that tells the household what is unsorted.
    household, account = _household_and_account(db)
    db.add(
        Transaction(
            household_id=household.id,
            account_id=account.id,
            posted_at=datetime(2026, 7, 1, tzinfo=UTC),
            amount=Decimal("-42.00"),
            currency="USD",
            merchant_raw="123456",
        )
    )
    db.commit()

    rows = categorization.uncategorized_merchants(db, household.id)
    assert [r.merchant for r in rows] == ["123456"]


def test_the_rollup_does_not_add_euros_to_dollars(db):
    household, account = _household_and_account(db)
    for currency in ("USD", "EUR"):
        db.add(
            Transaction(
                household_id=household.id,
                account_id=account.id,
                posted_at=datetime(2026, 7, 1, tzinfo=UTC),
                amount=Decimal("-100.00"),
                currency=currency,
                merchant_raw="SHELL OIL",
            )
        )
    db.commit()

    rows = categorization.uncategorized_merchants(db, household.id)
    assert {(r.currency, r.total) for r in rows} == {
        ("USD", Decimal("-100.00")),
        ("EUR", Decimal("-100.00")),
    }
