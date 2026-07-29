"""Price refresh — pulls a quote (or history) per security from the configured
provider and upserts into `security_prices`.

Resolution rule (spec §3.4): for a given (security, day), a `manual` row always wins
over a fetched one. Implemented as one `WHERE source != 'manual'` clause on the upsert's
conflict update, so a manual correction is never silently overwritten by the next
scheduler tick.

A missing price is not an error — `refresh`/`backfill` report the symbol in `failed` and
move on, matching the scheduler's "never raises, next tick catches up" posture.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.security import Security
from app.models.security_price import SecurityPrice
from app.providers.prices import PriceProvider, get_provider

log = logging.getLogger("openfinance.prices")


def _quote_symbol(security: Security) -> str:
    return security.quote_symbol or security.symbol


def _upsert(db: Session, security_id: uuid.UUID, priced_on: date, close: Decimal, source: str) -> None:
    stmt = insert(SecurityPrice).values(
        security_id=security_id, priced_on=priced_on, close=close, source=source
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["security_id", "priced_on"],
        set_={"close": stmt.excluded.close, "source": stmt.excluded.source},
        where=(SecurityPrice.source != "manual"),
    )
    db.execute(stmt)


def _priceable_securities(db: Session, household_id: uuid.UUID) -> list[Security]:
    return list(
        db.scalars(
            select(Security).where(
                Security.household_id == household_id, Security.is_manual_price.is_(False)
            )
        )
    )


@dataclass
class RefreshResult:
    updated: int = 0
    failed: list[str] = field(default_factory=list)


def refresh(
    db: Session, household_id: uuid.UUID, provider: PriceProvider | None = None
) -> RefreshResult:
    """Fetch today's quote for every non-manual security in the household."""
    provider = provider or get_provider()
    result = RefreshResult()
    today = datetime.now(UTC).date()
    for security in _priceable_securities(db, household_id):
        try:
            price = provider.quote(_quote_symbol(security))
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the rest
            log.warning("price fetch failed for %s: %s", security.symbol, exc)
            price = None
        if price is None:
            result.failed.append(security.symbol)
            continue
        _upsert(db, security.id, today, price, provider.name)
        result.updated += 1
    db.commit()
    return result


def backfill(
    db: Session, household_id: uuid.UUID, since: date, provider: PriceProvider | None = None
) -> RefreshResult:
    """Bulk-load history for every non-manual security — run after a CSV import so the
    performance tab has data from day one instead of building up over a year."""
    provider = provider or get_provider()
    result = RefreshResult()
    for security in _priceable_securities(db, household_id):
        try:
            series = provider.history(_quote_symbol(security), since)
        except Exception as exc:  # noqa: BLE001
            log.warning("history fetch failed for %s: %s", security.symbol, exc)
            series = []
        if not series:
            result.failed.append(security.symbol)
            continue
        for priced_on, close in series:
            _upsert(db, security.id, priced_on, close, provider.name)
        result.updated += 1
    db.commit()
    return result


def set_manual_price(db: Session, security_id: uuid.UUID, priced_on: date, close: Decimal) -> None:
    """The user correcting one bad close, or pricing an `is_manual_price` security."""
    stmt = insert(SecurityPrice).values(
        security_id=security_id, priced_on=priced_on, close=close, source="manual"
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["security_id", "priced_on"],
        set_={"close": stmt.excluded.close, "source": "manual"},
    )
    db.execute(stmt)
    db.commit()
