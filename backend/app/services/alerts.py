"""Things that need the household's attention, computed on read.

Nothing here is scheduled and no alert is stored: every call rebuilds the list from
rows that already exist, the same way budget rollover is computed on read. The only
state is AlertDismissal, keyed on a string that includes the date of the fact behind
the alert — dismissing one occurrence leaves the next one visible.

ponytail: thresholds are constants. Make one a household setting when someone asks to
change it, not before.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.alert_dismissal import AlertDismissal
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.transaction import Transaction
from app.services import budgets, forecast, recurring

BILL_DUE_DAYS = 3
YEARLY_RENEWAL_DAYS = 30
LOW_BALANCE_DAYS = 14
LARGE_CHARGE_LOOKBACK_DAYS = 7
LARGE_CHARGE_MULTIPLE = 3
LARGE_CHARGE_UNKNOWN_MERCHANT = Decimal(500)

Severity = Literal["info", "warn", "urgent"]
_SEVERITY_RANK: dict[str, int] = {"urgent": 0, "warn": 1, "info": 2}


class AlertKind(str, enum.Enum):
    bill_due = "bill_due"
    price_increase = "price_increase"
    yearly_renewal = "yearly_renewal"
    still_billing = "still_billing"
    low_balance = "low_balance"
    over_budget = "over_budget"
    large_charge = "large_charge"


@dataclass(frozen=True)
class Alert:
    key: str
    kind: AlertKind
    severity: Severity
    title: str
    body: str
    href: str
    occurred_on: date


def _key(kind: AlertKind, subject: object, on: date) -> str:
    return f"{kind.value}:{subject}:{on.isoformat()}"


def _upcoming(s: RecurringSeries, today: date, within_days: int) -> bool:
    return (
        s.status == SeriesStatus.active
        and s.direction < 0
        and s.next_expected_on is not None
        and today <= s.next_expected_on <= today + timedelta(days=within_days)
    )


def _from_series(
    db: Session, household_id: uuid.UUID, series: list[RecurringSeries], today: date
) -> list[Alert]:
    out: list[Alert] = []
    for s in series:
        # A yearly charge gets the longer-lead renewal alert instead of bill_due, never both.
        if s.cadence == Cadence.yearly and _upcoming(s, today, YEARLY_RENEWAL_DAYS):
            assert s.next_expected_on is not None
            out.append(
                Alert(
                    key=_key(AlertKind.yearly_renewal, s.id, s.next_expected_on),
                    kind=AlertKind.yearly_renewal,
                    severity="warn",
                    title=f"{s.label} renews soon",
                    body=f"About ${s.typical_amount:,.2f} expected on "
                    f"{s.next_expected_on.isoformat()}. Yearly charges are easy to forget.",
                    href="/recurring",
                    occurred_on=s.next_expected_on,
                )
            )
        elif s.cadence != Cadence.yearly and _upcoming(s, today, BILL_DUE_DAYS):
            assert s.next_expected_on is not None
            out.append(
                Alert(
                    key=_key(AlertKind.bill_due, s.id, s.next_expected_on),
                    kind=AlertKind.bill_due,
                    severity="info",
                    title=f"{s.label} is due soon",
                    body=f"About ${s.typical_amount:,.2f} expected on "
                    f"{s.next_expected_on.isoformat()}.",
                    href="/recurring",
                    occurred_on=s.next_expected_on,
                )
            )

        if s.status == SeriesStatus.active and s.price_increase_amount is not None:
            out.append(
                Alert(
                    key=_key(AlertKind.price_increase, s.id, s.last_charged_on),
                    kind=AlertKind.price_increase,
                    severity="warn",
                    title=f"{s.label} went up",
                    body=f"The last charge was ${s.price_increase_amount:,.2f} higher than usual.",
                    href="/recurring",
                    occurred_on=s.last_charged_on,
                )
            )

        if s.status == SeriesStatus.cancelled and s.cancelled_on is not None:
            charges = recurring.charges(db, household_id, s)
            if charges and charges[0].posted_at.date() > s.cancelled_on:
                charged_on = charges[0].posted_at.date()
                out.append(
                    Alert(
                        key=_key(AlertKind.still_billing, s.id, charged_on),
                        kind=AlertKind.still_billing,
                        severity="urgent",
                        title=f"{s.label} is still billing you",
                        body=f"You marked it cancelled on {s.cancelled_on.isoformat()}, "
                        f"but it charged ${abs(charges[0].amount):,.2f} on "
                        f"{charged_on.isoformat()}.",
                        href="/recurring",
                        occurred_on=charged_on,
                    )
                )
    return out


def _low_balance(db: Session, household_id: uuid.UUID, today: date) -> list[Alert]:
    horizon = today + timedelta(days=LOW_BALANCE_DAYS)
    for day in forecast.project(db, household_id, 1, today=today):
        if day.on > horizon:
            break
        if day.projected_balance < 0:
            when = "today" if day.on == today else f"on {day.on.isoformat()}"
            return [
                Alert(
                    # "cash" stands in for a subject id: the alert is about all cash
                    # accounts together, which is what the forecast sums.
                    key=_key(AlertKind.low_balance, "cash", day.on),
                    kind=AlertKind.low_balance,
                    severity="urgent",
                    title="Cash is projected to go negative",
                    body=f"Your cash accounts are projected at "
                    f"-${abs(day.projected_balance):,.2f} {when}.",
                    href="/",
                    occurred_on=day.on,
                )
            ]
    return []


def _over_budget(db: Session, household_id: uuid.UUID, today: date) -> list[Alert]:
    month = today.replace(day=1)
    return [
        Alert(
            key=_key(AlertKind.over_budget, row.category_id, month),
            kind=AlertKind.over_budget,
            severity="warn",
            title=f"{row.category_name} is over budget",
            body=f"${row.actual:,.2f} spent against ${row.effective_budget:,.2f} — "
            f"${row.actual - row.effective_budget:,.2f} over.",
            href="/budgets",
            occurred_on=month,
        )
        for row in budgets.status(db, household_id, month, today=today)
        # effective_budget > 0: spend in a category nobody budgeted is not "over".
        if row.effective_budget > 0 and row.actual > row.effective_budget
    ]


def _large_charges(
    db: Session, household_id: uuid.UUID, series: list[RecurringSeries], today: date
) -> list[Alert]:
    since = datetime.combine(
        today - timedelta(days=LARGE_CHARGE_LOOKBACK_DAYS), datetime.min.time(), tzinfo=UTC
    )
    txns = db.scalars(
        select(Transaction).where(
            Transaction.household_id == household_id,
            Transaction.posted_at >= since,
            Transaction.amount < 0,
        )
    )
    usual = {s.merchant_key: s.typical_amount for s in series if s.direction < 0}
    out: list[Alert] = []
    for t in txns:
        name = t.merchant_normalized or t.merchant_raw
        amount = abs(t.amount)
        typical = usual.get(recurring.merchant_key(name))
        if typical is not None:
            if amount < typical * LARGE_CHARGE_MULTIPLE:
                continue
            body = f"${amount:,.2f} — usually about ${typical:,.2f}."
        else:
            if amount < LARGE_CHARGE_UNKNOWN_MERCHANT:
                continue
            body = f"${amount:,.2f} from a merchant with no regular charges."
        on = t.posted_at.date()
        out.append(
            Alert(
                key=_key(AlertKind.large_charge, t.id, on),
                kind=AlertKind.large_charge,
                severity="info",
                title=f"Large charge from {name}",
                body=body,
                href="/transactions",
                occurred_on=on,
            )
        )
    return out


def dismiss(db: Session, household_id: uuid.UUID, key: str) -> None:
    """Idempotent, and deliberately does not check that `key` names a live alert: the
    alert may have resolved between the page load and the click."""
    db.execute(
        insert(AlertDismissal)
        .values(household_id=household_id, key=key)
        .on_conflict_do_nothing(constraint="uq_alert_dismissal")
    )
    db.commit()


def list_for(db: Session, household_id: uuid.UUID, *, today: date | None = None) -> list[Alert]:
    today = today or datetime.now(UTC).date()
    series = recurring.list_for(db, household_id, status=None)
    found = [
        *_from_series(db, household_id, series, today),
        *_low_balance(db, household_id, today),
        *_over_budget(db, household_id, today),
        *_large_charges(db, household_id, series, today),
    ]
    dismissed = set(
        db.scalars(select(AlertDismissal.key).where(AlertDismissal.household_id == household_id))
    )
    found = [a for a in found if a.key not in dismissed]
    # Two stable sorts: newest first, then by severity on top of that order.
    found.sort(key=lambda a: a.occurred_on, reverse=True)
    found.sort(key=lambda a: _SEVERITY_RANK[a.severity])
    return found
