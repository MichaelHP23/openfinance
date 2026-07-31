"""Rule-based transaction categorization.

Deterministic. No ML, no LLM in the matching path — the LLM only ever proposes rules
for a human to confirm (see `app/api/categories.py::suggest`).

Merchant matching runs against `recurring.merchant_key()`, the same normalization
subscription detection uses. That means "TST* WHOLE FOODS #4471" and "WHOLE FOODS
MARKET 22" reduce to comparable strings, and a rule the user writes once behaves the
same in both features. `merchant_contains` and `merchant_exact` patterns are normalized
with the same function on the way in, so the user can type "Whole Foods" and not think
about it. `merchant_regex` patterns are the exception: they run against the normalized
merchant name, but the pattern text itself is never passed through `merchant_key` — doing
so would destroy regex metacharacters (`.`, `*`, `(`, `|`, ...) — so a regex author writes
directly against the lowercased, punctuation-stripped merchant key and supplies their own
case-insensitivity if they need it.
"""

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category_rule import CategoryRule, MatchType
from app.models.transaction import Transaction
from app.schemas.category import RuleCreate, RuleUpdate
from app.services import categories
from app.services.recurring import merchant_key

# Patterns run against merchant keys, which are short. Capping the pattern keeps a
# pathological regex from having anything to chew on; there is no untrusted author here
# anyway, since the only writer is the household itself.
PATTERN_MAX = 200


class BadPattern(Exception):
    """A rule pattern that cannot be stored: empty, too long, or an invalid regex."""


def compile_pattern(match_type: MatchType, pattern: str) -> None:
    """Validate a pattern at write time. Raises BadPattern; returns nothing."""
    if not pattern or not pattern.strip():
        raise BadPattern("Pattern is empty")
    if len(pattern) > PATTERN_MAX:
        raise BadPattern(f"Pattern is longer than {PATTERN_MAX} characters")
    if match_type is MatchType.merchant_regex:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise BadPattern(f"Invalid regular expression: {exc}") from exc
    elif not merchant_key(pattern):
        # "#1234" normalizes to "" and `"" in name` is always True -> silent catch-all.
        raise BadPattern("Pattern has no letters or digits to match on")


def _merchant_of(txn: Transaction) -> str:
    return merchant_key(txn.merchant_normalized or txn.merchant_raw)


def rule_matches(rule: CategoryRule, txn: Transaction) -> bool:
    """True when every non-null condition on the rule holds for the transaction."""
    if rule.account_id is not None and rule.account_id != txn.account_id:
        return False
    if rule.min_amount is not None and txn.amount < rule.min_amount:
        return False
    if rule.max_amount is not None and txn.amount > rule.max_amount:
        return False

    name = _merchant_of(txn)
    if rule.match_type is MatchType.merchant_regex:
        try:
            return re.search(rule.pattern, name) is not None
        except re.error:
            # A stored pattern that no longer compiles is dead, not fatal. Skipping it
            # keeps every other rule working.
            return False
    needle = merchant_key(rule.pattern)
    if rule.match_type is MatchType.merchant_exact:
        return name == needle
    return needle in name


def pick_category(rules: list[CategoryRule], txn: Transaction) -> uuid.UUID | None:
    """First matching rule wins. Caller supplies the rules already in priority order."""
    for rule in rules:
        if rule_matches(rule, txn):
            return rule.category_id
    return None


def rules_for(db: Session, household_id: uuid.UUID) -> list[CategoryRule]:
    """Every rule for the household, in the order they should be tried."""
    return list(
        db.scalars(
            select(CategoryRule)
            .where(CategoryRule.household_id == household_id)
            .order_by(CategoryRule.priority, CategoryRule.created_at)
        )
    )


def apply_to(
    db: Session,
    household_id: uuid.UUID,
    txns: list[Transaction],
    rules: list[CategoryRule] | None = None,
) -> int:
    """Categorize supplied uncategorized rows in place without committing."""
    if rules is None:
        rules = rules_for(db, household_id)
    if not rules:
        return 0

    changed = 0
    for txn in txns:
        if txn.household_id != household_id:
            continue
        if txn.category_id is not None:
            continue
        category_id = pick_category(rules, txn)
        if category_id is not None:
            txn.category_id = category_id
            changed += 1
    return changed


def backfill(
    db: Session, household_id: uuid.UUID, *, only_uncategorized: bool = True
) -> int:
    """Apply the household's rules to historical transactions and commit the result."""
    query = select(Transaction).where(Transaction.household_id == household_id)
    if only_uncategorized:
        query = query.where(Transaction.category_id.is_(None))

    rules = rules_for(db, household_id)
    if not rules:
        return 0

    changed = 0
    for txn in db.scalars(query):
        category_id = pick_category(rules, txn)
        if category_id is not None and category_id != txn.category_id:
            txn.category_id = category_id
            changed += 1
    db.commit()
    return changed


@dataclass
class UncategorizedMerchant:
    merchant: str
    count: int
    total: Decimal


def uncategorized_merchants(
    db: Session, household_id: uuid.UUID, limit: int = 100
) -> list[UncategorizedMerchant]:
    """Roll uncategorized household transactions up by normalized merchant."""
    counts: dict[str, int] = defaultdict(int)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    rows = db.scalars(
        select(Transaction).where(
            Transaction.household_id == household_id,
            Transaction.category_id.is_(None),
        )
    )
    for txn in rows:
        merchant = _merchant_of(txn)
        if not merchant:
            continue
        counts[merchant] += 1
        totals[merchant] += txn.amount

    result = [
        UncategorizedMerchant(merchant=merchant, count=counts[merchant], total=totals[merchant])
        for merchant in counts
    ]
    result.sort(key=lambda item: (-item.count, item.merchant))
    return result[:limit]


class UnknownCategory(Exception):
    """A rule can only point at a category this household can actually see."""


def _check_category(db: Session, household_id: uuid.UUID, category_id: uuid.UUID) -> None:
    if categories.get(db, household_id, category_id) is None:
        raise UnknownCategory(str(category_id))


def _rule_row(household_id: uuid.UUID, data: RuleCreate) -> CategoryRule:
    return CategoryRule(
        household_id=household_id,
        match_type=data.match_type,
        pattern=data.pattern,
        category_id=data.category_id,
        min_amount=data.min_amount,
        max_amount=data.max_amount,
        account_id=data.account_id,
        priority=data.priority,
    )


def create_rule(db: Session, household_id: uuid.UUID, data: RuleCreate) -> CategoryRule:
    compile_pattern(data.match_type, data.pattern)
    _check_category(db, household_id, data.category_id)
    row = _rule_row(household_id, data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_rule(
    db: Session, household_id: uuid.UUID, rule_id: uuid.UUID
) -> CategoryRule | None:
    return db.scalar(
        select(CategoryRule).where(
            CategoryRule.id == rule_id, CategoryRule.household_id == household_id
        )
    )


def update_rule(
    db: Session, household_id: uuid.UUID, rule_id: uuid.UUID, data: RuleUpdate
) -> CategoryRule | None:
    row = get_rule(db, household_id, rule_id)
    if row is None:
        return None
    fields = data.model_dump(exclude_unset=True)
    compile_pattern(
        fields.get("match_type", row.match_type), fields.get("pattern", row.pattern)
    )
    if "category_id" in fields:
        _check_category(db, household_id, fields["category_id"])
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def delete_rule(db: Session, household_id: uuid.UUID, rule_id: uuid.UUID) -> bool:
    row = get_rule(db, household_id, rule_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def reorder(db: Session, household_id: uuid.UUID, rule_ids: list[uuid.UUID]) -> int:
    """Rewrite priority to match the given order. Ids not listed keep their place at
    the end, in their existing order."""
    by_id = {r.id: r for r in rules_for(db, household_id)}
    listed = set(rule_ids)
    ordered = [by_id[i] for i in rule_ids if i in by_id]
    ordered += [r for r in by_id.values() if r.id not in listed]
    for index, row in enumerate(ordered):
        row.priority = (index + 1) * 10
    db.commit()
    return len(ordered)


def preview(db: Session, household_id: uuid.UUID, data: RuleCreate) -> int:
    """How many existing transactions a rule would match. Writes nothing."""
    compile_pattern(data.match_type, data.pattern)
    candidate = _rule_row(household_id, data)
    # Never added to the session, but autoflush would still try to persist it the moment
    # the query below runs, so the read is explicitly held outside the flush.
    with db.no_autoflush:
        txns = db.scalars(
            select(Transaction).where(Transaction.household_id == household_id)
        )
        return sum(1 for t in txns if rule_matches(candidate, t))
