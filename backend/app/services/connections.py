import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import ConnStatus, Provider, ProviderConnection
from app.providers.simplefin import SimpleFinProvider
from app.services.sync import SyncResult, sync_connection


def list_for(db: Session, household_id: uuid.UUID) -> list[ProviderConnection]:
    return list(
        db.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.household_id == household_id)
            .order_by(ProviderConnection.created_at)
        )
    )


def get(
    db: Session, household_id: uuid.UUID, connection_id: uuid.UUID
) -> ProviderConnection | None:
    return db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == connection_id,
            ProviderConnection.household_id == household_id,
        )
    )


def link_simplefin(
    db: Session,
    household_id: uuid.UUID,
    setup_token: str,
    provider: SimpleFinProvider | None = None,
) -> ProviderConnection:
    provider = provider or SimpleFinProvider()
    conn = provider.link_account(household_id, {"setup_token": setup_token})
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def sync(
    db: Session,
    household_id: uuid.UUID,
    conn: ProviderConnection,
    provider: SimpleFinProvider | None = None,
    *,
    full: bool = False,
) -> SyncResult:
    if conn.provider is not Provider.simplefin:
        raise ValueError(f"No sync implemented for {conn.provider.value}")
    try:
        return sync_connection(db, household_id, conn, provider or SimpleFinProvider(), full=full)
    except Exception:
        conn.status = ConnStatus.error
        db.commit()
        raise


def delete(db: Session, household_id: uuid.UUID, connection_id: uuid.UUID) -> bool:
    """Forget a connection and its stored credentials. Imported rows stay put."""
    conn = get(db, household_id, connection_id)
    if not conn:
        return False
    db.delete(conn)
    db.commit()
    return True
