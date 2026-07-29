"""Periodic sync + daily balance snapshot.

ponytail: an asyncio timer inside the API process, not a job queue. Good enough for a
single-user install — if it misses a tick because the container was down, the next tick
catches up, and snapshots are idempotent per day. Move to Dramatiq (Redis is already
here) if this ever needs retries, backoff, or more than one worker.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.connection import Provider, ProviderConnection
from app.models.household import Household
from app.services import connections as connections_service
from app.services import prices as prices_service
from app.services import recurring as recurring_service
from app.services import snapshots as snapshots_service

log = logging.getLogger("openfinance.scheduler")


def run_once() -> None:
    """Sync every linked connection, then record today's balances. Never raises."""
    db = SessionLocal()
    try:
        for household_id in db.scalars(select(Household.id)):
            conns = db.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.household_id == household_id,
                    ProviderConnection.provider == Provider.simplefin,
                )
            )
            for conn in conns:
                try:
                    result = connections_service.sync(db, household_id, conn)
                    log.info(
                        "synced %s: +%d accounts, +%d transactions",
                        conn.id,
                        result.accounts_added,
                        result.transactions_added,
                    )
                except Exception as exc:  # noqa: BLE001 - one bad bank must not stop the rest
                    log.warning("sync failed for %s: %s", conn.id, exc)

            try:
                snapshots_service.capture(db, household_id)
            except Exception as exc:  # noqa: BLE001 - a failed snapshot is not fatal
                log.warning("snapshot failed for %s: %s", household_id, exc)

            try:
                recurring_service.detect(db, household_id)
            except Exception as exc:  # noqa: BLE001 - one bad household must not stop the loop
                log.warning("recurring detection failed for %s: %s", household_id, exc)

            # ponytail: `settings.price_refresh_hours` (default 24) is not enforced with
            # a last-fetched timestamp — refresh() upserts on (security, day), so calling
            # it on every tick (default every 6h) just re-fetches the same day's quote a
            # few times. Harmless for Yahoo (no stated limit) and well inside Twelve
            # Data's 800/day. Add a last-refreshed check if that ever stops being true.
            try:
                result = prices_service.refresh(db, household_id)
                if result.failed:
                    log.info(
                        "price refresh for %s: +%d updated, failed: %s",
                        household_id,
                        result.updated,
                        result.failed,
                    )
            except Exception as exc:  # noqa: BLE001 - a stale price is not fatal
                log.warning("price refresh failed for %s: %s", household_id, exc)
    finally:
        db.close()


async def _loop() -> None:
    interval = settings.sync_interval_hours * 3600
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive any single tick
            log.warning("scheduler tick failed: %s", exc)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task: asyncio.Task[None] | None = None
    if settings.sync_interval_hours > 0:
        task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
