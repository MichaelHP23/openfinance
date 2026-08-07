"""The AI advisor's tool registry.

Every tool here is a thin, read-only wrapper over a service function that already
existed before P4 — nothing in this module writes to the database, and nothing takes
raw SQL. `ALLOWED_TOOLS` is the allowlist tests/test_advisor_tools.py asserts the
registry against, so a mutation function can never quietly become reachable from the
model by being added to `_REGISTRY` under a plausible-sounding name.

Money in a tool result is a rounded float, not a Decimal — the same one-way,
read-only exception services/digest.py already made for the LLM's JSON payload (see
Global Constraints in this plan's own document for why that isn't a violation of
"money is Decimal, never float").
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.models.recurring import SeriesStatus
from app.services import budgets as budgets_service
from app.services import categories as categories_service
from app.services import forecast as forecast_service
from app.services import goals as goals_service
from app.services import portfolio as portfolio_service
from app.services import recurring as recurring_service
from app.services import transactions as transactions_service
from app.services.snapshots import net_worth_series


def _money(value: Any) -> float:
    return round(float(value), 2)


class NetWorthHistoryArgs(BaseModel):
    months: int = Field(default=6, ge=1, le=60)


def _net_worth_history(
    db: Session, household_id: uuid.UUID, args: NetWorthHistoryArgs
) -> dict[str, Any]:
    points = net_worth_series(db, household_id, days=args.months * 30)
    return {
        "points": [
            {
                "on": p.on.isoformat(),
                "assets": _money(p.assets),
                "debts": _money(p.debts),
                "net": _money(p.net),
            }
            for p in points
        ]
    }


class HoldingsSummaryArgs(BaseModel):
    pass


def _holdings_summary(
    db: Session, household_id: uuid.UUID, args: HoldingsSummaryArgs
) -> dict[str, Any]:
    result = portfolio_service.holdings(db, household_id)
    return {
        "totals": {k: _money(v) for k, v in result.totals.items()},
        "priced_through": result.priced_through.isoformat() if result.priced_through else None,
        "holdings": [
            {
                "symbol": h.symbol,
                "name": h.name,
                "units": _money(h.units),
                "market_value": _money(h.market_value) if h.market_value is not None else None,
                "unrealized_pct": _money(h.unrealized_pct) if h.unrealized_pct is not None else None,
                "share_pct": _money(h.share_pct) if h.share_pct is not None else None,
            }
            for h in result.holdings
        ],
    }


class RecurringListArgs(BaseModel):
    status: Literal["active", "ended", "cancelled", "ignored"] | None = None


def _recurring_list(
    db: Session, household_id: uuid.UUID, args: RecurringListArgs
) -> dict[str, Any]:
    status = SeriesStatus(args.status) if args.status else None
    rows = recurring_service.list_for(db, household_id, status=status)
    return {
        "series": [
            {
                "label": s.label,
                "cadence": s.cadence.value,
                "status": s.status.value,
                "direction": s.direction,
                "typical_amount": _money(s.typical_amount),
                "next_expected_on": s.next_expected_on.isoformat() if s.next_expected_on else None,
                "confidence": s.confidence,
            }
            for s in rows
        ]
    }


class SpendByCategoryArgs(BaseModel):
    start: date
    end: date
    group_by: Literal["category", "month"] = "category"


def _spend_by_category(
    db: Session, household_id: uuid.UUID, args: SpendByCategoryArgs
) -> dict[str, Any]:
    since = datetime.combine(args.start, datetime.min.time(), tzinfo=UTC)
    until = datetime.combine(args.end, datetime.max.time(), tzinfo=UTC)
    txns = transactions_service.list_for(db, household_id, since=since, until=until)
    spend = [t for t in txns if t.amount < 0]

    if args.group_by == "month":
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for t in spend:
            totals[t.posted_at.strftime("%Y-%m")] += -t.amount
        ranked = sorted(totals.items())
        return {"by": "month", "totals": [{"key": k, "amount": _money(v)} for k, v in ranked]}

    names: dict[uuid.UUID | None, str] = {
        c.id: c.name for c in categories_service.list_for(db, household_id)
    }
    by_name: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for t in spend:
        label = names.get(t.category_id, "Uncategorized")
        by_name[label] += -t.amount
    ranked = sorted(by_name.items(), key=lambda kv: kv[1], reverse=True)
    return {"by": "category", "totals": [{"key": k, "amount": _money(v)} for k, v in ranked]}


class TransactionSearchArgs(BaseModel):
    merchant: str | None = None
    category: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    start: date | None = None
    end: date | None = None
    limit: int = Field(default=20, ge=1, le=50)


def _transaction_search(
    db: Session, household_id: uuid.UUID, args: TransactionSearchArgs
) -> dict[str, Any]:
    """The only tool that returns individual transactions, and the only one capped
    below the household's whole history — 50 rows, per the spec. `merchant` reuses
    transactions.list_for's own `search` filter (an ilike over merchant_raw), which is
    P1's, not extended here; category, amount, and the row cap are applied on top
    since list_for doesn't support them."""
    since = datetime.combine(args.start, datetime.min.time(), tzinfo=UTC) if args.start else None
    until = datetime.combine(args.end, datetime.max.time(), tzinfo=UTC) if args.end else None
    txns = transactions_service.list_for(
        db, household_id, since=since, until=until, search=args.merchant
    )

    if args.category:
        wanted = next(
            (
                c.id
                for c in categories_service.list_for(db, household_id)
                if c.name.lower() == args.category.lower()
            ),
            None,
        )
        txns = [t for t in txns if t.category_id == wanted] if wanted else []
    if args.min_amount is not None:
        txns = [t for t in txns if t.amount >= args.min_amount]
    if args.max_amount is not None:
        txns = [t for t in txns if t.amount <= args.max_amount]

    rows = txns[: args.limit]
    return {
        "count": len(rows),
        "transactions": [
            {
                "date": t.posted_at.date().isoformat(),
                "merchant": t.merchant_normalized or t.merchant_raw,
                "amount": _money(t.amount),
            }
            for t in rows
        ],
    }


class BudgetStatusArgs(BaseModel):
    month: str  # "YYYY-MM"


def _budget_status(db: Session, household_id: uuid.UUID, args: BudgetStatusArgs) -> dict[str, Any]:
    month = budgets_service.parse_month(args.month)
    rows = budgets_service.status(db, household_id, month)
    return {
        "month": args.month,
        "categories": [
            {
                "category": r.category_name,
                "budgeted": _money(r.budgeted),
                "actual": _money(r.actual),
                "remaining": _money(r.remaining),
                "pace": r.pace,
            }
            for r in rows
        ],
    }


class CashflowForecastArgs(BaseModel):
    months: int = Field(default=6, ge=1, le=24)
    hypothetical_amount: Decimal | None = None
    hypothetical_date: date | None = None


def _cashflow_forecast(
    db: Session, household_id: uuid.UUID, args: CashflowForecastArgs
) -> dict[str, Any]:
    hyps = None
    if args.hypothetical_amount is not None and args.hypothetical_date is not None:
        hyps = [forecast_service.Hypothetical(amount=args.hypothetical_amount, on_date=args.hypothetical_date)]
    days = forecast_service.project(db, household_id, args.months, hyps)
    if not days:
        return {"days_projected": 0, "ending_balance": 0.0, "minimum_balance": 0.0, "first_negative_day": None}
    minimum = min(d.projected_balance for d in days)
    first_negative = next((d.on for d in days if d.projected_balance < 0), None)
    return {
        "days_projected": len(days),
        "ending_balance": _money(days[-1].projected_balance),
        "minimum_balance": _money(minimum),
        "first_negative_day": first_negative.isoformat() if first_negative else None,
    }


class GoalProgressArgs(BaseModel):
    pass


def _goal_progress(db: Session, household_id: uuid.UUID, args: GoalProgressArgs) -> dict[str, Any]:
    overview = forecast_service.goals_overview(db, household_id)
    by_id = {g.id: g for g in goals_service.list_for(db, household_id)}
    return {
        "goals": [
            {
                "name": by_id[o.goal_id].name,
                "kind": by_id[o.goal_id].kind.value,
                "target_amount": _money(by_id[o.goal_id].target_amount),
                "progress": _money(o.progress),
                "projected_date": o.projected_date.isoformat() if o.projected_date else None,
            }
            for o in overview
            if o.goal_id in by_id
        ]
    }


_DESCRIPTIONS: dict[str, str] = {
    "net_worth_history": "Net worth (assets, debts, net) per recorded day over the trailing N months.",
    "holdings_summary": "Current investment holdings: units, market value, unrealized gain, share of portfolio.",
    "recurring_list": "Recurring charges and deposits, optionally filtered by status.",
    "spend_by_category": "Total spending in a date range, grouped by category or by month. Aggregates only.",
    "transaction_search": (
        "Search individual transactions by merchant, category, amount range, and date "
        "range. Returns at most 50 rows — the only tool that returns individual "
        "transactions; everything else here returns aggregates."
    ),
    "budget_status": "Budgeted vs. actual spend, remaining amount, and pace for every category in a given month.",
    "cashflow_forecast": "Projected cash balance over N months, optionally with one hypothetical purchase or deposit.",
    "goal_progress": "Progress and projected completion date for every active savings or debt-payoff goal.",
}

# name -> (Pydantic argument schema, wrapper function). Order here is the order
# TOOL_SPECS is presented to the model in.
_REGISTRY: dict[str, tuple[type[BaseModel], Any]] = {
    "net_worth_history": (NetWorthHistoryArgs, _net_worth_history),
    "holdings_summary": (HoldingsSummaryArgs, _holdings_summary),
    "recurring_list": (RecurringListArgs, _recurring_list),
    "spend_by_category": (SpendByCategoryArgs, _spend_by_category),
    "transaction_search": (TransactionSearchArgs, _transaction_search),
    "budget_status": (BudgetStatusArgs, _budget_status),
    "cashflow_forecast": (CashflowForecastArgs, _cashflow_forecast),
    "goal_progress": (GoalProgressArgs, _goal_progress),
}

ALLOWED_TOOLS: tuple[str, ...] = tuple(_REGISTRY.keys())


def _spec_for(name: str, schema: type[BaseModel]) -> dict[str, Any]:
    return {"name": name, "description": _DESCRIPTIONS[name], "input_schema": schema.model_json_schema()}


TOOL_SPECS: list[dict[str, Any]] = [_spec_for(name, schema) for name, (schema, _fn) in _REGISTRY.items()]


def run_tool(
    name: str, raw_args: dict[str, Any], db: Session, household_id: uuid.UUID
) -> dict[str, Any]:
    """Validate and dispatch one tool call. Never raises: an unknown name, invalid
    arguments, or a wrapper's own bug all become an `{"error": ...}` result the model
    sees, so one failing tool call cannot kill the whole turn."""
    entry = _REGISTRY.get(name)
    if entry is None:
        return {"error": f"unknown tool: {name}"}

    schema, fn = entry
    try:
        args = schema.model_validate(raw_args)
    except ValidationError as exc:
        return {"error": f"invalid arguments: {exc}"}

    try:
        result: dict[str, Any] = fn(db, household_id, args)
        return result
    except Exception as exc:  # noqa: BLE001 - a tool's own bug must not kill the turn
        return {"error": f"{name} failed: {exc}"}
