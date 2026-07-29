"""Recurring & subscription detection.

Deterministic, no ML, no LLM — the whole heuristic is arithmetic over transaction dates
and amounts, run whole over a household's last 18 months on every scheduler tick and on
demand via `POST /recurring/refresh`. At one household's volume ("a few thousand rows")
that's cheap enough that incremental detection would only add a reconciliation bug, so
`detect()` recomputes every candidate from scratch and upserts.

No `recurring_charges` join table: the charges belonging to a series are found by
recomputing `merchant_key` over the household's transactions at read time (see
`charges()`). That's cheaper than maintaining a link table detection would have to keep
in sync.
"""

import re
import statistics
import uuid
from calendar import monthrange
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.models.transaction import Transaction
from app.schemas.recurring import SeriesUpdate

# How far back detect() looks. 18 months is enough to see a yearly charge twice, which
# is the minimum needed to say anything about its cadence at all.
LOOKBACK_DAYS = 548
MIN_CHARGES = 3
MIN_SPAN_DAYS = 21
MIN_CADENCE_SCORE = 0.60
# Chosen to keep a quarterly series with one missed cycle in, and a pair of
# coincidentally-same-amount unrelated charges out. See §5.2 of the design doc.
MIN_CONFIDENCE = 55
# A price bump only counts if it clears both a dollar floor and a relative floor —
# otherwise routine cent-level variance (a bill with tax) reads as a "price increase".
PRICE_INCREASE_MIN_ABS = Decimal("1.00")
PRICE_INCREASE_MIN_PCT = Decimal("0.10")

# (low, high) day-gap bucket each cadence has to land in to be classified as that cadence.
CADENCE_BUCKETS: dict[Cadence, tuple[int, int]] = {
    Cadence.weekly: (5, 9),
    Cadence.biweekly: (12, 16),
    Cadence.monthly: (25, 35),
    Cadence.quarterly: (80, 100),
    Cadence.yearly: (350, 380),
}
_MONTHS_PER_CADENCE = {Cadence.monthly: 1, Cadence.quarterly: 3, Cadence.yearly: 12}
# Decimal multipliers to normalize a charge of each cadence onto a monthly figure.
_MONTHLY_MULTIPLIER: dict[Cadence, Decimal] = {
    Cadence.weekly: Decimal(52) / Decimal(12),
    Cadence.biweekly: Decimal(26) / Decimal(12),
    Cadence.monthly: Decimal(1),
    Cadence.quarterly: Decimal(1) / Decimal(3),
    Cadence.yearly: Decimal(1) / Decimal(12),
}

_LEADING_PREFIXES = ("pos debit ", "ach debit ", "sq *", "tst* ", "pp*")
_LEGAL_SUFFIXES = {"llc", "inc", "corp", "co", "ltd"}

# ponytail: "last detected at" is process-memory only, not a DB column — the model in
# the design doc explicitly rules out audit columns. Lost on a restart; the scheduler
# re-runs within SYNC_INTERVAL_HOURS anyway so it self-heals. Upgrade path: a tiny
# key/value metadata table (or Redis, already in the stack) if cross-restart accuracy
# ever matters.
_last_detected_at: dict[uuid.UUID, datetime] = {}


@dataclass
class DetectionResult:
    detected: int
    updated: int
    ended: int
    removed: int


@dataclass
class Summary:
    monthly_committed: Decimal
    monthly_incoming: Decimal
    active_count: int
    upcoming: list[dict[str, object]]
    price_increases: int
    last_detected_at: datetime | None


@dataclass
class _Candidate:
    label: str
    account_id: uuid.UUID | None
    cadence: Cadence
    direction: int
    typical_amount: Decimal
    last_amount: Decimal
    min_amount: Decimal
    max_amount: Decimal
    amount_varies: bool
    price_increase_amount: Decimal | None
    charge_count: int
    first_charged_on: date
    last_charged_on: date
    next_expected_on: date
    confidence: int
    median_gap_days: int


def merchant_key(name: str) -> str:
    """Reduce a raw merchant string to a stable grouping key.

    Not written to the database in SP1 — SP2 owns `merchant_normalized`. Because this
    is computed from `merchant_normalized or merchant_raw` at call sites, SP2 improves
    every series here for free with no change to this function.
    """
    key = (name or "").lower().strip()
    for prefix in _LEADING_PREFIXES:
        if key.startswith(prefix):
            key = key[len(prefix) :]
            break
    key = re.sub(r"#\d+", " ", key)  # "#4471" style store numbers
    key = re.sub(r"\d{3,}", " ", key)  # any other run of 3+ digits (refs, terminal ids)
    key = re.sub(r"[^a-z0-9]+", " ", key)
    tokens = [t for t in key.split() if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _group(txns: Iterable[Transaction]) -> dict[tuple[str, int], list[Transaction]]:
    """Bucket transactions by (merchant_key, sign(amount)).

    Sign matters: a paycheck and a refund from the same employer are different series.
    """
    groups: dict[tuple[str, int], list[Transaction]] = defaultdict(list)
    for t in txns:
        key = merchant_key(t.merchant_normalized or t.merchant_raw)
        direction = 1 if t.amount >= 0 else -1
        groups[(key, direction)].append(t)
    return groups


def _dedupe_same_day(txns: Iterable[Transaction]) -> list[Transaction]:
    """Collapse same-day duplicates within a group, keeping the larger charge."""
    by_day: dict[date, Transaction] = {}
    for t in txns:
        day = t.posted_at.date()
        existing = by_day.get(day)
        if existing is None or abs(t.amount) > abs(existing.amount):
            by_day[day] = t
    return sorted(by_day.values(), key=lambda t: t.posted_at)


def _classify_cadence(median_gap: float) -> Cadence | None:
    for cadence, (lo, hi) in CADENCE_BUCKETS.items():
        if lo <= median_gap <= hi:
            return cadence
    return None


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])  # clamp e.g. the 31st in a 30-day month
    return date(year, month, day)


def _next_expected_on(last_charged_on: date, cadence: Cadence, median_gap_days: int) -> date:
    months = _MONTHS_PER_CADENCE.get(cadence)
    if months is not None:
        return _add_months(last_charged_on, months)
    return last_charged_on + timedelta(days=median_gap_days)


def _past_grace(next_expected_on: date, median_gap_days: int, today: date) -> bool:
    grace = max(7, median_gap_days // 2)
    return today > next_expected_on + timedelta(days=grace)


def _build_candidate(txns: list[Transaction]) -> _Candidate | None:
    charges = _dedupe_same_day(txns)
    if len(charges) < MIN_CHARGES:
        return None

    span_days = (charges[-1].posted_at.date() - charges[0].posted_at.date()).days
    if span_days < MIN_SPAN_DAYS:
        return None

    gaps = [
        (b.posted_at.date() - a.posted_at.date()).days for a, b in zip(charges, charges[1:])
    ]
    median_gap = float(statistics.median(gaps))
    cadence = _classify_cadence(median_gap)
    if cadence is None:
        return None

    lo, hi = CADENCE_BUCKETS[cadence]
    in_bucket = 0
    at_multiple = 0
    for g in gaps:
        if lo <= g <= hi:
            in_bucket += 1
            continue
        n = round(g / median_gap) if median_gap else 0
        if n >= 2 and lo * n <= g <= hi * n:
            at_multiple += 1
    cadence_score = (in_bucket + 0.5 * at_multiple) / len(gaps)
    if cadence_score < MIN_CADENCE_SCORE:
        return None

    amounts = sorted(abs(t.amount) for t in charges)
    typical_amount = statistics.median(amounts)
    min_amount, max_amount = amounts[0], amounts[-1]
    spread = (max_amount - min_amount) / typical_amount if typical_amount else Decimal(0)
    if spread <= Decimal("0.05"):
        amount_score = 1.0
    elif spread <= Decimal("0.25"):
        amount_score = 0.8
    elif spread <= Decimal("1.00"):
        amount_score = 0.5
    else:
        return None
    amount_varies = spread > Decimal("0.25")

    count_score = min(len(charges), 6) / 6
    confidence = round(100 * (0.50 * cadence_score + 0.30 * amount_score + 0.20 * count_score))
    if confidence < MIN_CONFIDENCE:
        return None

    last = charges[-1]
    last_amount = abs(last.amount)
    prior_amounts = sorted(abs(t.amount) for t in charges[:-1])
    price_increase_amount: Decimal | None = None
    if prior_amounts:
        prior_median = statistics.median(prior_amounts)
        diff = last_amount - prior_median
        if (
            prior_median > 0
            and diff >= PRICE_INCREASE_MIN_ABS
            and diff >= prior_median * PRICE_INCREASE_MIN_PCT
        ):
            price_increase_amount = diff

    median_gap_days = round(median_gap)
    last_charged_on = last.posted_at.date()
    next_expected_on = _next_expected_on(last_charged_on, cadence, median_gap_days)

    account_counts = Counter(t.account_id for t in charges)
    account_id = account_counts.most_common(1)[0][0] if account_counts else None

    return _Candidate(
        label=last.merchant_normalized or last.merchant_raw,
        account_id=account_id,
        cadence=cadence,
        direction=1 if last.amount >= 0 else -1,
        typical_amount=typical_amount,
        last_amount=last_amount,
        min_amount=min_amount,
        max_amount=max_amount,
        amount_varies=amount_varies,
        price_increase_amount=price_increase_amount,
        charge_count=len(charges),
        first_charged_on=charges[0].posted_at.date(),
        last_charged_on=last_charged_on,
        next_expected_on=next_expected_on,
        confidence=confidence,
        median_gap_days=median_gap_days,
    )


def _apply_candidate(row: RecurringSeries, candidate: _Candidate) -> None:
    """Overwrite every derived field. Never touches label, status, cancel_url, notes —
    those are the user-owned fields that survive a re-run."""
    row.account_id = candidate.account_id
    row.cadence = candidate.cadence
    row.direction = candidate.direction
    row.typical_amount = candidate.typical_amount
    row.last_amount = candidate.last_amount
    row.min_amount = candidate.min_amount
    row.max_amount = candidate.max_amount
    row.amount_varies = candidate.amount_varies
    row.price_increase_amount = candidate.price_increase_amount
    row.charge_count = candidate.charge_count
    row.first_charged_on = candidate.first_charged_on
    row.last_charged_on = candidate.last_charged_on
    row.next_expected_on = candidate.next_expected_on
    row.confidence = candidate.confidence


def _is_user_touched(row: RecurringSeries) -> bool:
    """Whether a row carries anything the user set by hand.

    ponytail: a rename alone doesn't count — there's no stored "default label" to diff
    against, so a plain rename can't protect a row from deletion once it stops
    detecting. Combine a rename with "ignore" if you want to keep it around anyway.
    """
    return (
        row.status in (SeriesStatus.cancelled, SeriesStatus.ignored)
        or row.cancel_url is not None
        or row.notes is not None
    )


def detect(db: Session, household_id: uuid.UUID) -> DetectionResult:
    """Rebuild the household's recurring series from transaction history.

    Idempotent and whole-table: cheap enough at one household's volume that
    incremental detection would only add a reconciliation bug.
    """
    since = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id, Transaction.posted_at >= since
            )
        )
    )

    candidates: dict[str, _Candidate] = {}
    for (key, _direction), group_txns in _group(txns).items():
        if not key:
            continue
        candidate = _build_candidate(group_txns)
        if candidate is None:
            continue
        existing = candidates.get(key)
        if existing is None or candidate.charge_count > existing.charge_count:
            # ponytail: the table is unique on (household_id, merchant_key) only, not
            # direction, so a merchant name that's identical between an outgoing and
            # an incoming series collides here — the stronger signal (more charges)
            # wins and the other is dropped for this run. Real households essentially
            # never produce the same normalized name for a paycheck and a refund.
            # Upgrade path: add `direction` to the unique constraint if it ever bites.
            candidates[key] = candidate

    existing_rows = {
        row.merchant_key: row
        for row in db.scalars(
            select(RecurringSeries).where(RecurringSeries.household_id == household_id)
        )
    }

    today = datetime.now(UTC).date()
    detected = updated = ended = removed = 0

    for key, candidate in candidates.items():
        row = existing_rows.get(key)
        if row is None:
            row = RecurringSeries(
                household_id=household_id, merchant_key=key, label=candidate.label
            )
            db.add(row)
            detected += 1
        else:
            updated += 1
        _apply_candidate(row, candidate)

        if row.status not in (SeriesStatus.cancelled, SeriesStatus.ignored):
            new_status = (
                SeriesStatus.ended
                if _past_grace(candidate.next_expected_on, candidate.median_gap_days, today)
                else SeriesStatus.active
            )
            if new_status != row.status:
                if new_status == SeriesStatus.ended:
                    ended += 1
                row.status = new_status

    for key, row in existing_rows.items():
        if key in candidates:
            continue
        if _is_user_touched(row):
            if row.status not in (SeriesStatus.cancelled, SeriesStatus.ignored, SeriesStatus.ended):
                row.status = SeriesStatus.ended
                ended += 1
        else:
            db.delete(row)
            removed += 1

    db.commit()
    _last_detected_at[household_id] = datetime.now(UTC)
    return DetectionResult(detected=detected, updated=updated, ended=ended, removed=removed)


def list_for(
    db: Session, household_id: uuid.UUID, *, status: SeriesStatus | None = None
) -> list[RecurringSeries]:
    q = select(RecurringSeries).where(RecurringSeries.household_id == household_id)
    if status is not None:
        q = q.where(RecurringSeries.status == status)
    return list(db.scalars(q.order_by(RecurringSeries.label)))


def get(db: Session, household_id: uuid.UUID, series_id: uuid.UUID) -> RecurringSeries | None:
    return db.scalar(
        select(RecurringSeries).where(
            RecurringSeries.id == series_id, RecurringSeries.household_id == household_id
        )
    )


def charges(db: Session, household_id: uuid.UUID, series: RecurringSeries) -> list[Transaction]:
    """Every transaction whose merchant key and sign match this series, newest first.

    Recomputed at read time rather than joined off a link table — see the module
    docstring.
    """
    txns = list(
        db.scalars(select(Transaction).where(Transaction.household_id == household_id))
    )
    matching = [
        t
        for t in txns
        if merchant_key(t.merchant_normalized or t.merchant_raw) == series.merchant_key
        and (1 if t.amount >= 0 else -1) == series.direction
    ]
    return sorted(matching, key=lambda t: t.posted_at, reverse=True)


def update(
    db: Session, household_id: uuid.UUID, series_id: uuid.UUID, data: SeriesUpdate
) -> RecurringSeries | None:
    """Rename, ignore, or mark cancelled. Detection never overwrites these."""
    row = get(db, household_id, series_id)
    if row is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "status" and value is not None:
            value = SeriesStatus(value)
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def monthly_committed(series: list[RecurringSeries], *, direction: int = -1) -> Decimal:
    """Active series in one direction, normalized to a per-month figure.

    Decimal throughout: weekly x 52/12, biweekly x 26/12, quarterly / 3, yearly / 12,
    quantized to cents at the end so the total doesn't drift.
    """
    total = Decimal(0)
    for s in series:
        if s.status != SeriesStatus.active or s.direction != direction:
            continue
        total += s.typical_amount * _MONTHLY_MULTIPLIER[s.cadence]
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def summary(db: Session, household_id: uuid.UUID) -> Summary:
    active = list_for(db, household_id, status=SeriesStatus.active)
    today = datetime.now(UTC).date()
    horizon = today + timedelta(days=30)
    upcoming = sorted(
        (s for s in active if s.next_expected_on and today <= s.next_expected_on <= horizon),
        key=lambda s: s.next_expected_on,  # type: ignore[arg-type,return-value]
    )
    return Summary(
        monthly_committed=monthly_committed(active, direction=-1),
        monthly_incoming=monthly_committed(active, direction=1),
        active_count=len(active),
        upcoming=[
            {"id": s.id, "label": s.label, "on": s.next_expected_on, "amount": s.last_amount}
            for s in upcoming
        ],
        price_increases=sum(1 for s in active if s.price_increase_amount is not None),
        last_detected_at=_last_detected_at.get(household_id),
    )
