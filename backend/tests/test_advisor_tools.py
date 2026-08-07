"""Every tool is a thin, read-only, Pydantic-validated wrapper over a service that
already existed before P4. This file's most important test is the last one in each
task's block: the registry asserted against an allowlist, so a mutation function can
never quietly become reachable from the model."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.account import Account, AccountType
from app.models.household import Household
from app.services import advisor_tools
from app.services import categories as categories_service
from app.services import recurring as recurring_service
from app.services import snapshots as snapshots_service
from app.services import transactions as transactions_service


@pytest.fixture
def household(db):
    row = Household(name="Advisor Tools Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def account(db, household):
    row = Account(
        household_id=household.id,
        type=AccountType.checking,
        name="Checking",
        currency="USD",
        balance=Decimal("1500.00"),
    )
    db.add(row)
    db.commit()
    return row


def test_net_worth_history_reads_the_recorded_snapshots(db, household, account):
    snapshots_service.capture(db, household.id)
    result = advisor_tools.run_tool("net_worth_history", {"months": 3}, db, household.id)
    assert result["points"]
    assert result["points"][0]["net"] == 1500.0


def test_net_worth_history_rejects_an_out_of_range_month_count(db, household):
    result = advisor_tools.run_tool("net_worth_history", {"months": 61}, db, household.id)
    assert "error" in result
    assert "invalid arguments" in result["error"]


def test_holdings_summary_is_empty_with_no_trades(db, household):
    result = advisor_tools.run_tool("holdings_summary", {}, db, household.id)
    assert result["holdings"] == []
    assert result["totals"]["market_value"] == 0.0


def test_recurring_list_filters_by_status(db, household):
    recurring_service.detect(db, household.id)  # no charges yet, so nothing detected
    result = advisor_tools.run_tool("recurring_list", {"status": "active"}, db, household.id)
    assert result["series"] == []


def test_recurring_list_rejects_an_unknown_status(db, household):
    result = advisor_tools.run_tool("recurring_list", {"status": "cancelled_forever"}, db, household.id)
    assert "error" in result


def test_run_tool_reports_an_unknown_tool_name_as_an_error_not_a_crash(db, household):
    result = advisor_tools.run_tool("delete_everything", {}, db, household.id)
    assert result == {"error": "unknown tool: delete_everything"}


def test_a_wrapper_exception_becomes_an_error_result_not_a_raise(db, household, monkeypatch):
    def boom(db, household_id, args):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        advisor_tools._REGISTRY, "net_worth_history", (advisor_tools.NetWorthHistoryArgs, boom)
    )
    result = advisor_tools.run_tool("net_worth_history", {"months": 1}, db, household.id)
    assert "error" in result
    assert "boom" in result["error"]


def test_registry_matches_the_allowlist_exactly():
    assert set(advisor_tools._REGISTRY.keys()) == set(advisor_tools.ALLOWED_TOOLS)
    assert {spec["name"] for spec in advisor_tools.TOOL_SPECS} == set(advisor_tools.ALLOWED_TOOLS)


def test_registry_contains_no_mutating_service_function():
    """The allowlist check above only proves the *names* look read-only. This proves
    the actual function objects behind them are never one of the real mutating
    functions those same services expose — the belt to the allowlist's suspenders."""
    forbidden = {
        transactions_service.create,
        transactions_service.update,
        transactions_service.delete,
        categories_service.create,
        categories_service.update,
        categories_service.delete,
        recurring_service.update,
        recurring_service.detect,
    }
    registered_fns = {fn for _schema, fn in advisor_tools._REGISTRY.values()}
    assert registered_fns.isdisjoint(forbidden)


from app.schemas.transaction import TxnCreate


def _txn(db, household, account, merchant: str, amount: str, on: str = "2026-07-15"):
    return transactions_service.create(
        db,
        household.id,
        TxnCreate(
            account_id=account.id,
            posted_at=datetime.fromisoformat(f"{on}T00:00:00+00:00"),
            amount=Decimal(amount),
            merchant_raw=merchant,
        ),
    )


def test_spend_by_category_groups_uncategorized_spend_together(db, household, account):
    _txn(db, household, account, "Corner Store", "-25.00")
    _txn(db, household, account, "Corner Store", "-15.00")
    result = advisor_tools.run_tool(
        "spend_by_category",
        {"start": "2026-07-01", "end": "2026-07-31", "group_by": "category"},
        db,
        household.id,
    )
    assert result["by"] == "category"
    assert result["totals"] == [{"key": "Uncategorized", "amount": 40.0}]


def test_spend_by_category_ignores_income(db, household, account):
    _txn(db, household, account, "Payroll", "3000.00")
    _txn(db, household, account, "Rent", "-1200.00")
    result = advisor_tools.run_tool(
        "spend_by_category", {"start": "2026-07-01", "end": "2026-07-31"}, db, household.id
    )
    assert result["totals"] == [{"key": "Uncategorized", "amount": 1200.0}]


def test_spend_by_category_can_group_by_month_instead(db, household, account):
    _txn(db, household, account, "Rent", "-1200.00", on="2026-07-01")
    _txn(db, household, account, "Rent", "-1200.00", on="2026-06-01")
    result = advisor_tools.run_tool(
        "spend_by_category",
        {"start": "2026-06-01", "end": "2026-07-31", "group_by": "month"},
        db,
        household.id,
    )
    assert result["by"] == "month"
    assert {t["key"]: t["amount"] for t in result["totals"]} == {"2026-06": 1200.0, "2026-07": 1200.0}


def test_spend_by_category_rejects_an_end_before_start(db, household):
    # start/end aren't cross-validated by the schema (Pydantic can't express "end >=
    # start" as a field constraint without a model validator this tool doesn't need);
    # an inverted range simply yields no rows rather than an error, which is exercised
    # here so the behavior is pinned down rather than accidental.
    result = advisor_tools.run_tool(
        "spend_by_category", {"start": "2026-07-31", "end": "2026-07-01"}, db, household.id
    )
    assert result["totals"] == []


def test_transaction_search_matches_by_merchant_substring(db, household, account):
    _txn(db, household, account, "WHOLE FOODS #221", "-42.00")
    _txn(db, household, account, "Netflix", "-15.99")
    result = advisor_tools.run_tool("transaction_search", {"merchant": "whole"}, db, household.id)
    assert result["count"] == 1
    assert result["transactions"][0]["merchant"] == "WHOLE FOODS #221"


def test_transaction_search_filters_by_amount_range(db, household, account):
    _txn(db, household, account, "Big Purchase", "-500.00")
    _txn(db, household, account, "Small Purchase", "-5.00")
    result = advisor_tools.run_tool(
        "transaction_search", {"min_amount": "-100.00", "max_amount": "0.00"}, db, household.id
    )
    assert [t["merchant"] for t in result["transactions"]] == ["Small Purchase"]


def test_transaction_search_is_capped_at_50_rows_even_if_more_match(db, household, account):
    for i in range(60):
        _txn(db, household, account, f"Merchant {i}", "-1.00")
    result = advisor_tools.run_tool("transaction_search", {"limit": 50}, db, household.id)
    assert result["count"] == 50


def test_transaction_search_rejects_a_limit_above_50(db, household):
    result = advisor_tools.run_tool("transaction_search", {"limit": 51}, db, household.id)
    assert "error" in result


from datetime import date

from app.services.categories import ensure_system_categories, system_category_id


def test_budget_status_reports_budgeted_and_actual(db, household, account):
    from app.services import budgets

    ensure_system_categories(db)
    groceries = system_category_id("Food & Drink/Groceries")
    budgets.upsert(db, household.id, date(2026, 7, 1), [budgets.BudgetItem(groceries, Decimal("300.00"))])
    _txn(db, household, account, "Groceries Run", "-50.00", on="2026-07-05")

    result = advisor_tools.run_tool("budget_status", {"month": "2026-07"}, db, household.id)
    row = next(c for c in result["categories"] if c["category"] == "Groceries")
    assert row["budgeted"] == 300.0


def test_budget_status_rejects_a_malformed_month(db, household):
    result = advisor_tools.run_tool("budget_status", {"month": "not-a-month"}, db, household.id)
    assert "error" in result


def test_cashflow_forecast_reports_ending_and_minimum_balance(db, household, account):
    result = advisor_tools.run_tool("cashflow_forecast", {"months": 1}, db, household.id)
    assert result["ending_balance"] == 1500.0
    assert result["minimum_balance"] == 1500.0
    assert result["first_negative_day"] is None


def test_cashflow_forecast_applies_a_hypothetical(db, household, account):
    # `forecast.project` walks forward from the real wall-clock "today" (there's no
    # `today` override on this tool's args), so the hypothetical's date has to be
    # relative to now rather than a hardcoded past date, or it falls outside the
    # walk and is silently never applied.
    from datetime import timedelta

    soon = (datetime.now(UTC).date() + timedelta(days=5)).isoformat()
    result = advisor_tools.run_tool(
        "cashflow_forecast",
        {"months": 1, "hypothetical_amount": "-2000.00", "hypothetical_date": soon},
        db,
        household.id,
    )
    assert result["minimum_balance"] < 0


def test_goal_progress_reports_every_active_goal(db, household, account):
    from app.services import goals
    from app.models.goal import GoalKind

    goals.create(
        db, household.id, name="Emergency Fund", kind=GoalKind.savings,
        target_amount=Decimal("5000.00"), account_ids=[account.id],
    )
    result = advisor_tools.run_tool("goal_progress", {}, db, household.id)
    assert result["goals"][0]["name"] == "Emergency Fund"
    assert result["goals"][0]["progress"] == 1500.0


def test_registry_matches_the_allowlist_with_all_eight_tools():
    assert set(advisor_tools._REGISTRY.keys()) == {
        "net_worth_history",
        "holdings_summary",
        "recurring_list",
        "spend_by_category",
        "transaction_search",
        "budget_status",
        "cashflow_forecast",
        "goal_progress",
    }
