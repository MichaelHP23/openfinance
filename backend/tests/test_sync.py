import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.connection import ConnStatus, Provider, ProviderConnection
from app.models.household import Household
from app.providers.base import AccountDTO, TxnDTO, set_credentials
from app.services import accounts as accounts_service
from app.services import transactions as txn_service
from app.services.sync import sync_connection


class FakeProvider:
    """Returns whatever it's told to, so sync can be tested without any network."""

    name = "fake"

    def __init__(self, accounts, txns):
        self._accounts = accounts
        self._txns = txns
        self.since_seen: list[datetime | None] = []

    def link_account(self, household_id, credentials):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_accounts(self, conn):
        return self._accounts

    def fetch_transactions(self, conn, since):
        self.since_seen.append(since)
        return self._txns


def _household(db) -> uuid.UUID:
    """Connections carry a real FK to households, so tests need a real row."""
    household = Household(name="Test Household")
    db.add(household)
    db.commit()
    return household.id


def _conn(db, household_id) -> ProviderConnection:
    conn = ProviderConnection(household_id=household_id, provider=Provider.simplefin)
    set_credentials(conn, {"access_url": "https://u:p@example.test/simplefin"})
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


ACCOUNTS = [
    AccountDTO(
        external_id="a1",
        name="Checking",
        type="checking",
        currency="USD",
        balance=Decimal("100.00"),
    ),
    AccountDTO(
        external_id="a2",
        name="Card",
        type="credit_card",
        currency="USD",
        balance=Decimal("-50.00"),
    ),
]

TXNS = [
    TxnDTO(
        external_id="t1",
        account_external_id="a1",
        posted_at=datetime(2026, 5, 1, tzinfo=UTC),
        amount=Decimal("-9.99"),
        currency="USD",
        merchant_raw="Coffee",
    ),
    TxnDTO(
        external_id="t2",
        account_external_id="a2",
        posted_at=datetime(2026, 5, 2, tzinfo=UTC),
        amount=Decimal("-20.00"),
        currency="USD",
        merchant_raw="Books",
    ),
]


def test_first_sync_creates_accounts_and_transactions(db):
    hid = _household(db)
    conn = _conn(db, hid)
    result = sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, TXNS))

    assert result.accounts_added == 2
    assert result.transactions_added == 2
    assert result.transactions_skipped == 0

    rows = accounts_service.list_for(db, hid)
    assert {a.name for a in rows} == {"Checking", "Card"}
    assert all(a.is_manual is False for a in rows)
    assert len(txn_service.list_for(db, hid)) == 2


def test_second_sync_updates_balances_and_skips_known_transactions(db):
    hid = _household(db)
    conn = _conn(db, hid)
    sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, TXNS))

    moved = [
        AccountDTO(
            external_id="a1",
            name="Checking",
            type="checking",
            currency="USD",
            balance=Decimal("250.00"),
        ),
        ACCOUNTS[1],
    ]
    result = sync_connection(db, hid, conn, FakeProvider(moved, TXNS))

    assert result.accounts_added == 0
    assert result.accounts_updated == 2
    assert result.transactions_added == 0
    assert result.transactions_skipped == 2

    balances = {a.name: a.balance for a in accounts_service.list_for(db, hid)}
    assert balances["Checking"] == Decimal("250.0000")
    assert len(txn_service.list_for(db, hid)) == 2


def test_new_transactions_arrive_on_a_later_sync(db):
    hid = _household(db)
    conn = _conn(db, hid)
    sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, TXNS))

    extra = TxnDTO(
        external_id="t3",
        account_external_id="a1",
        posted_at=datetime(2026, 5, 9, tzinfo=UTC),
        amount=Decimal("-4.00"),
        currency="USD",
        merchant_raw="Bagel",
    )
    result = sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, [*TXNS, extra]))

    assert result.transactions_added == 1
    assert result.transactions_skipped == 2
    assert len(txn_service.list_for(db, hid)) == 3


def test_sync_passes_the_last_sync_time_as_since(db):
    hid = _household(db)
    conn = _conn(db, hid)
    provider = FakeProvider(ACCOUNTS, TXNS)

    sync_connection(db, hid, conn, provider)
    assert provider.since_seen == [None]  # nothing synced yet

    sync_connection(db, hid, conn, provider)
    assert provider.since_seen[1] is not None


def test_sync_stamps_last_synced_and_marks_the_connection_active(db):
    hid = _household(db)
    conn = _conn(db, hid)
    conn.status = ConnStatus.error
    db.commit()

    sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, TXNS))
    assert conn.last_synced_at is not None
    assert conn.status is ConnStatus.active


def test_transactions_for_unlisted_accounts_are_reported_not_dropped_silently(db):
    hid = _household(db)
    conn = _conn(db, hid)
    orphan = TxnDTO(
        external_id="t9",
        account_external_id="ghost",
        posted_at=datetime(2026, 5, 3, tzinfo=UTC),
        amount=Decimal("-1.00"),
        currency="USD",
        merchant_raw="Ghost",
    )
    result = sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, [orphan]))

    assert result.transactions_added == 0
    assert result.errors == ["Unknown account ghost"]


def test_sync_refuses_a_connection_from_another_household(db):
    owner, intruder = _household(db), uuid.uuid4()
    conn = _conn(db, owner)
    with pytest.raises(ValueError, match="another household"):
        sync_connection(db, intruder, conn, FakeProvider(ACCOUNTS, TXNS))


def test_synced_rows_are_invisible_to_other_households(db):
    hid, other = _household(db), uuid.uuid4()
    conn = _conn(db, hid)
    sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, TXNS))

    assert accounts_service.list_for(db, other) == []
    assert txn_service.list_for(db, other) == []


def _txn(ext: str, day: int, amount: str, merchant: str, account: str = "a1") -> TxnDTO:
    return TxnDTO(
        external_id=ext,
        account_external_id=account,
        posted_at=datetime(2026, 5, day, tzinfo=UTC),
        amount=Decimal(amount),
        currency="USD",
        merchant_raw=merchant,
    )


def test_reissued_ids_do_not_multiply_rows(db):
    """SimpleFIN's demo re-ids every transaction per call, and real providers re-id a
    pending charge when it posts. Neither should duplicate what we already hold."""
    hid = _household(db)
    conn = _conn(db, hid)

    sync_connection(
        db, hid, conn, FakeProvider(ACCOUNTS, [_txn("id-1", 1, "-6.65", "Grocery store")])
    )
    result = sync_connection(
        db, hid, conn, FakeProvider(ACCOUNTS, [_txn("id-999", 1, "-6.65", "Grocery store")])
    )

    assert result.transactions_added == 0
    assert result.transactions_skipped == 1
    assert len(txn_service.list_for(db, hid)) == 1


def test_two_genuinely_identical_purchases_are_both_kept(db):
    """Buying the same coffee twice in a day is real; the provider reports two, so we
    keep two rather than collapsing them."""
    hid = _household(db)
    conn = _conn(db, hid)

    both = [_txn("c-1", 2, "-5.50", "Coffee"), _txn("c-2", 2, "-5.50", "Coffee")]
    result = sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, both))

    assert result.transactions_added == 2
    assert len(txn_service.list_for(db, hid)) == 2


def test_a_third_identical_purchase_later_still_registers(db):
    hid = _household(db)
    conn = _conn(db, hid)
    sync_connection(
        db,
        hid,
        conn,
        FakeProvider(
            ACCOUNTS, [_txn("c-1", 2, "-5.50", "Coffee"), _txn("c-2", 2, "-5.50", "Coffee")]
        ),
    )

    again = [
        _txn("x-1", 2, "-5.50", "Coffee"),
        _txn("x-2", 2, "-5.50", "Coffee"),
        _txn("x-3", 2, "-5.50", "Coffee"),
    ]
    result = sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, again))

    assert result.transactions_added == 1
    assert result.transactions_skipped == 2
    assert len(txn_service.list_for(db, hid)) == 3


def test_repeated_syncs_are_stable(db):
    """The bug this replaced turned 6 transactions into 18 across three syncs."""
    hid = _household(db)
    conn = _conn(db, hid)
    batch = [
        _txn("a", 1, "-6.65", "Grocery store"),
        _txn("b", 1, "-5.50", "Grocery store"),
        _txn("c", 3, "-176.67", "John's Fishin Shack"),
    ]
    for run in range(3):
        reissued = [
            TxnDTO(
                external_id=f"{t.external_id}-{run}",
                account_external_id=t.account_external_id,
                posted_at=t.posted_at,
                amount=t.amount,
                currency=t.currency,
                merchant_raw=t.merchant_raw,
            )
            for t in batch
        ]
        sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, reissued))

    assert len(txn_service.list_for(db, hid)) == 3


def test_a_different_amount_on_the_same_day_is_not_a_duplicate(db):
    hid = _household(db)
    conn = _conn(db, hid)
    sync_connection(db, hid, conn, FakeProvider(ACCOUNTS, [_txn("p-1", 4, "-10.00", "Shop")]))
    result = sync_connection(
        db, hid, conn, FakeProvider(ACCOUNTS, [_txn("p-2", 4, "-12.00", "Shop")])
    )
    assert result.transactions_added == 1
