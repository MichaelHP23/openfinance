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
