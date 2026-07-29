"""CRUD for `securities` — the ticker list a household's trades reference."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security import Security
from app.models.trade import Trade
from app.schemas.investment import SecurityCreate, SecurityUpdate


class SecurityInUseError(Exception):
    """A trade still references this security — deleting it would orphan history."""


def list_for(db: Session, household_id: uuid.UUID) -> list[Security]:
    return list(
        db.scalars(
            select(Security)
            .where(Security.household_id == household_id)
            .order_by(Security.symbol)
        )
    )


def get(db: Session, household_id: uuid.UUID, security_id: uuid.UUID) -> Security | None:
    return db.scalar(
        select(Security).where(Security.id == security_id, Security.household_id == household_id)
    )


def get_by_symbol(db: Session, household_id: uuid.UUID, symbol: str) -> Security | None:
    return db.scalar(
        select(Security).where(
            Security.household_id == household_id, Security.symbol == symbol.strip().upper()
        )
    )


def get_or_create(
    db: Session, household_id: uuid.UUID, symbol: str, currency: str = "USD"
) -> Security:
    """Resolve a typed symbol to a Security row, creating one if unknown.

    Shared by the trade API (`symbol` -> `security_id`) and the CSV importer — both
    match on the uppercased symbol, per `Security`'s docstring.
    """
    symbol = symbol.strip().upper()
    existing = get_by_symbol(db, household_id, symbol)
    if existing is not None:
        return existing
    security = Security(household_id=household_id, symbol=symbol, currency=currency)
    db.add(security)
    db.flush()
    return security


def create(db: Session, household_id: uuid.UUID, data: SecurityCreate) -> Security:
    symbol = data.symbol.strip().upper()
    if get_by_symbol(db, household_id, symbol) is not None:
        raise ValueError(f"Security {symbol} already exists")
    security = Security(
        household_id=household_id,
        symbol=symbol,
        name=data.name,
        currency=data.currency,
        is_manual_price=data.is_manual_price,
    )
    db.add(security)
    db.commit()
    db.refresh(security)
    return security


def update(
    db: Session, household_id: uuid.UUID, security_id: uuid.UUID, data: SecurityUpdate
) -> Security | None:
    security = get(db, household_id, security_id)
    if security is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(security, field, value)
    db.commit()
    db.refresh(security)
    return security


def delete(db: Session, household_id: uuid.UUID, security_id: uuid.UUID) -> bool:
    security = get(db, household_id, security_id)
    if security is None:
        return False
    in_use = db.scalar(select(Trade.id).where(Trade.security_id == security_id).limit(1))
    if in_use is not None:
        raise SecurityInUseError(f"Security {security.symbol} has trades against it")
    db.delete(security)
    db.commit()
    return True
