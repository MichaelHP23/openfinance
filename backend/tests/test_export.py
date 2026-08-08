import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.models  # ensure the full registry is populated
from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.account import Account, AccountType
from app.models.base import Base
from app.models.household import Household
from app.models.transaction import Transaction

app.state.limiter.enabled = False

# Hardcoded independently of `app.services.export.EXCLUDED_TABLES` on purpose — a new
# household-scoped model must be consciously routed to a CSV or added to *both* lists
# with a stated reason, not silently inherited by whichever list already exists.
EXPECTED_EXCLUDED_TABLES = {"users", "provider_connections"}


@pytest.fixture
def household(db):
    row = Household(name="Export Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def other_household(db):
    row = Household(name="Other Export Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db, household):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_household] = lambda: household.id
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def test_export_contains_a_csv_for_every_household_owned_table(client, db, household):
    all_household_tables = {
        name for name, table in Base.metadata.tables.items() if "household_id" in table.columns
    }
    expected_csvs = all_household_tables - EXPECTED_EXCLUDED_TABLES

    res = client.get("/export/all.zip")
    assert res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = {n[:-4] for n in zf.namelist() if n.endswith(".csv")}
    assert names == expected_csvs


def test_export_contains_only_the_requesting_household_rows(client, db, household, other_household):
    account = Account(household_id=household.id, type=AccountType.checking, name="Mine", currency="USD")
    other_account = Account(household_id=other_household.id, type=AccountType.checking, name="Theirs", currency="USD")
    db.add_all([account, other_account])
    db.commit()
    db.add_all(
        [
            Transaction(household_id=household.id, account_id=account.id,
                        posted_at=datetime(2026, 1, 1, tzinfo=UTC), amount=Decimal("-1.00"),
                        currency="USD", merchant_raw="Mine"),
            Transaction(household_id=other_household.id, account_id=other_account.id,
                        posted_at=datetime(2026, 1, 1, tzinfo=UTC), amount=Decimal("-2.00"),
                        currency="USD", merchant_raw="Theirs"),
        ]
    )
    db.commit()

    res = client.get("/export/all.zip")
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    txns_csv = zf.read("transactions.csv").decode()
    assert "Mine" in txns_csv
    assert "Theirs" not in txns_csv
