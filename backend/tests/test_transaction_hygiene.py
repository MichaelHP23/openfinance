"""P12: `ignored` and `tags` on transactions.

The first half is one test per spending aggregate: an ignored transaction must not move
its number. Each seeds a counted row next to the ignored one, so a test cannot pass by
the aggregate simply being empty.
"""

import csv
import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.household import Household
from app.models.transaction import Transaction
from app.services import (
    advisor_tools,
    alerts,
    budgets,
    digest,
    export,
    recurring,
    reports,
    transactions,
)
from app.services.alerts import AlertKind
from app.services.categories import ensure_system_categories, system_category_id
from tests.csrf_helper import csrf_client

app.state.limiter.enabled = False

GROCERIES = system_category_id("Food & Drink/Groceries")


@pytest.fixture
def household(db):
    row = Household(name="Hygiene Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(household_id=household.id, type=AccountType.checking, name="Everyday", currency="USD")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    app.dependency_overrides[require_household] = lambda: household.id
    yield csrf_client(app, db, get_db)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def _txn(db, household, account, amount, merchant, on, *, ignored=False, tags=None, category_id=None):
    when = on if isinstance(on, datetime) else datetime(on.year, on.month, on.day, tzinfo=UTC)
    row = Transaction(
        household_id=household.id,
        account_id=account.id,
        posted_at=when,
        amount=Decimal(amount),
        currency="USD",
        merchant_raw=merchant,
        category_id=category_id,
        ignored=ignored,
        tags=tags or [],
    )
    db.add(row)
    db.commit()
    return row


# --- ignored: one test per aggregate -------------------------------------------------


def test_new_transaction_is_not_ignored_and_has_no_tags(db, household, account):
    t = _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1))
    db.refresh(t)
    assert t.ignored is False
    assert t.tags == []


def test_ignored_transaction_stays_in_the_list(db, household, account):
    _txn(db, household, account, "-900.00", "Sofa Barn", date(2026, 7, 2), ignored=True)
    assert [t.merchant_raw for t in transactions.list_for(db, household.id)] == ["Sofa Barn"]


def test_ignored_leaves_budget_actuals(db, household, account):
    ensure_system_categories(db)
    budgets.upsert(db, household.id, date(2026, 7, 1), [budgets.BudgetItem(GROCERIES, Decimal("300.00"))])
    _txn(db, household, account, "-50.00", "Market", date(2026, 7, 5), category_id=GROCERIES)
    _txn(db, household, account, "-900.00", "Market", date(2026, 7, 6), category_id=GROCERIES, ignored=True)
    rows = budgets.status(db, household.id, date(2026, 7, 1), today=date(2026, 7, 31))
    row = next(r for r in rows if r.category_id == GROCERIES)
    assert row.actual == Decimal("50.00")


def test_ignored_leaves_report_spending(db, household, account):
    _txn(db, household, account, "-50.00", "Market", date(2026, 7, 5))
    _txn(db, household, account, "-900.00", "Sofa Barn", date(2026, 7, 6), ignored=True)
    buckets = reports.spending(db, household.id, date(2026, 7, 1), date(2026, 7, 31), "merchant")
    assert [(b.key, b.total) for b in buckets] == [("market", Decimal("50.00"))]


def test_ignored_leaves_income_vs_expense(db, household, account):
    now = datetime.now(UTC)
    _txn(db, household, account, "-50.00", "Market", now)
    _txn(db, household, account, "-900.00", "Sofa Barn", now, ignored=True)
    _txn(db, household, account, "5000.00", "Own Transfer", now, ignored=True)
    this_month = reports.income_vs_expense(db, household.id, months=1)[0]
    assert (this_month.income, this_month.expense) == (Decimal("0.00"), Decimal("50.00"))


def test_ignored_leaves_year_in_review(db, household, account):
    _txn(db, household, account, "1000.00", "Employer", date(2026, 3, 1))
    _txn(db, household, account, "-50.00", "Market", date(2026, 3, 5))
    _txn(db, household, account, "-900.00", "Sofa Barn", date(2026, 3, 6), ignored=True)
    review = reports.year_in_review(db, household.id, 2026)
    assert review.total_out == Decimal("50.00")
    assert review.biggest_transaction_merchant == "Market"


def test_ignored_leaves_the_digest(db, household, account):
    now = datetime.now(UTC)
    _txn(db, household, account, "-50.00", "Market", now)
    _txn(db, household, account, "-900.00", "Sofa Barn", now, ignored=True)
    d = digest.build(db, household.id)
    assert [m.spending for m in d.months] == [50.0]
    assert [m.merchant for m in d.top_merchants] == ["Market"]
    assert [t["merchant"] for t in d.largest_transactions] == ["Market"]


def test_ignored_leaves_advisor_spend_by_category(db, household, account):
    _txn(db, household, account, "-50.00", "Market", date(2026, 7, 5))
    _txn(db, household, account, "-900.00", "Sofa Barn", date(2026, 7, 6), ignored=True)
    result = advisor_tools.run_tool(
        "spend_by_category", {"start": "2026-07-01", "end": "2026-07-31"}, db, household.id
    )
    assert result["totals"] == [{"key": "Uncategorized", "amount": 50.0}]


def test_advisor_transaction_search_marks_ignored_rows(db, household, account):
    # The model sums what it is shown; it has to be told which rows not to count.
    _txn(db, household, account, "-900.00", "Sofa Barn", date(2026, 7, 6), ignored=True)
    result = advisor_tools.run_tool("transaction_search", {}, db, household.id)
    assert result["transactions"][0]["ignored"] is True


def test_ignored_charges_do_not_form_a_recurring_series(db, household, account):
    now = datetime.now(UTC)
    rows = [
        _txn(db, household, account, "-15.99", "Netflix", now - timedelta(days=d))
        for d in (95, 65, 35, 5)
    ]
    assert recurring.detect(db, household.id).detected == 1
    for t in rows:
        t.ignored = True
    db.commit()
    recurring.detect(db, household.id)
    assert recurring.list_for(db, household.id) == []


def test_ignored_large_charge_does_not_alert(db, household, account):
    today = date(2026, 10, 12)
    _txn(db, household, account, "-600.00", "Lamp Hut", date(2026, 10, 10))
    _txn(db, household, account, "-900.00", "Sofa Barn", date(2026, 10, 10), ignored=True)
    found = [a for a in alerts.list_for(db, household.id, today=today) if a.kind == AlertKind.large_charge]
    assert len(found) == 1
    assert "Lamp Hut" in found[0].title


# --- API: ignore and tags -------------------------------------------------------------


def test_patch_sets_ignored(client, db, household, account):
    t = _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1))
    res = client.patch(f"/transactions/{t.id}", json={"ignored": True})
    assert res.status_code == 200
    assert res.json()["ignored"] is True


def test_patch_normalizes_tags(client, db, household, account):
    t = _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1))
    res = client.patch(f"/transactions/{t.id}", json={"tags": ["  Tax ", "reimbursable", "TAX"]})
    assert res.status_code == 200
    assert res.json()["tags"] == ["tax", "reimbursable"]


@pytest.mark.parametrize(
    "tags",
    [
        ["x" * 33],
        [f"t{i}" for i in range(11)],
        ["   "],
        None,
    ],
    ids=["too-long", "too-many", "blank", "null"],
)
def test_patch_rejects_bad_tags(client, db, household, account, tags):
    t = _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1))
    assert client.patch(f"/transactions/{t.id}", json={"tags": tags}).status_code == 422


def test_patch_rejects_null_ignored(client, db, household, account):
    t = _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1))
    assert client.patch(f"/transactions/{t.id}", json={"ignored": None}).status_code == 422


def test_patch_without_the_new_fields_leaves_them_alone(client, db, household, account):
    t = _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1), ignored=True, tags=["tax"])
    res = client.patch(f"/transactions/{t.id}", json={"notes": "lunch"})
    assert (res.json()["ignored"], res.json()["tags"]) == (True, ["tax"])


def test_list_filters_by_tag(client, db, household, account):
    _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1), tags=["tax"])
    _txn(db, household, account, "-2.00", "Store", date(2026, 7, 2), tags=["taxi"])
    _txn(db, household, account, "-3.00", "Other", date(2026, 7, 3))
    res = client.get("/transactions", params={"tag": " Tax "})
    assert [t["merchant_raw"] for t in res.json()] == ["Cafe"]


def test_tags_endpoint_lists_distinct_tags_for_this_household_only(client, db, household, account):
    other = Household(name="Other")
    db.add(other)
    db.commit()
    other_account = Account(household_id=other.id, type=AccountType.checking, name="Theirs", currency="USD")
    db.add(other_account)
    db.commit()
    _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1), tags=["tax", "work"])
    _txn(db, household, account, "-2.00", "Store", date(2026, 7, 2), tags=["tax"])
    _txn(db, other, other_account, "-3.00", "Theirs", date(2026, 7, 3), tags=["secret"])
    assert client.get("/transactions/tags").json() == ["tax", "work"]


def test_export_carries_ignored_and_tags(db, household, account):
    _txn(db, household, account, "-1.00", "Cafe", date(2026, 7, 1), ignored=True, tags=["tax", "work"])
    zf = zipfile.ZipFile(io.BytesIO(export.build_zip(db, household.id)))
    row = next(csv.DictReader(io.StringIO(zf.read("transactions.csv").decode())))
    assert (row["ignored"], row["tags"]) == ("True", "tax;work")


def test_series_charges_carry_ignored_and_tags(client, db, household, account):
    # The series view renders charges with the ledger's own row, toggle and tag field
    # included; without these it would always show them as unset.
    now = datetime.now(UTC)
    for d in (95, 65, 35):
        _txn(db, household, account, "-15.99", "Netflix", now - timedelta(days=d))
    recurring.detect(db, household.id)
    _txn(db, household, account, "-15.99", "Netflix", now - timedelta(days=5), ignored=True, tags=["tax"])
    series_id = recurring.list_for(db, household.id)[0].id
    newest = client.get(f"/recurring/{series_id}").json()["charges"][0]
    assert (newest["ignored"], newest["tags"]) == (True, ["tax"])
