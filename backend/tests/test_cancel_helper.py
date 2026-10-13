"""P11 — known cancel links, platform-billed subscriptions, and cancelled_on.

Spec: docs/superpowers/specs/2026-10-12-rocket-money-features-design.md §4.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.api.deps import require_household
from app.core.db import get_db
from app.main import app
from app.models.household import Household
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus
from app.schemas.recurring import SeriesUpdate
from app.services import cancel_links, recurring
from tests.csrf_helper import csrf_client

app.state.limiter.enabled = False


# --- cancel_links: pure lookups -------------------------------------------------------


def test_known_merchant_gets_its_own_cancellation_page():
    help_ = cancel_links.lookup("Netflix")
    assert help_ is not None
    assert "netflix.com" in help_.url
    assert help_.via is None


def test_lookup_survives_bank_noise_around_the_merchant_name():
    help_ = cancel_links.lookup("POS DEBIT NETFLIX.COM #4471")
    assert help_ is not None and "netflix.com" in help_.url


@pytest.mark.parametrize(
    ("label", "via"),
    [
        ("APPLE.COM/BILL", "Apple"),
        ("GOOGLE *YouTube Premium", "Google Play"),
        ("PAYPAL *SPOTIFY", "PayPal"),
        ("ROKU FOR HULU", "Roku"),
        ("AMZN Digital*Paramount", "Amazon"),
    ],
)
def test_platform_billed_charge_points_at_the_platform_not_the_merchant(label, via):
    help_ = cancel_links.lookup(label)
    assert help_ is not None
    assert help_.via == via
    assert help_.steps


def test_unknown_merchant_has_no_help():
    assert cancel_links.lookup("Joe's Corner Gym") is None


def test_a_merchant_name_inside_a_longer_word_does_not_match():
    # "max" is a streaming service; "Maxwell Hardware" is not.
    assert cancel_links.lookup("Maxwell Hardware") is None


def test_every_link_is_https():
    urls = [*cancel_links.MERCHANT_LINKS.values(), *(p.url for p in cancel_links.PLATFORMS)]
    assert urls and all(u.startswith("https://") for u in urls)


# --- cancelled_on ---------------------------------------------------------------------


@pytest.fixture
def household(db):
    row = Household(name="Cancel Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def series(db, household):
    row = RecurringSeries(
        household_id=household.id, merchant_key="netflix", label="Netflix",
        cadence=Cadence.monthly, status=SeriesStatus.active, direction=-1,
        typical_amount=Decimal("15.49"), last_amount=Decimal("15.49"),
        min_amount=Decimal("15.49"), max_amount=Decimal("15.49"), charge_count=6,
        first_charged_on=date(2026, 2, 14), last_charged_on=date(2026, 9, 14),
        next_expected_on=date(2026, 10, 14), confidence=90,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _today() -> date:
    return datetime.now(UTC).date()


def test_marking_cancelled_records_the_day(db, household, series):
    row = recurring.update(db, household.id, series.id, SeriesUpdate(status="cancelled"))
    assert row.cancelled_on == _today()


def test_putting_it_back_clears_the_day(db, household, series):
    recurring.update(db, household.id, series.id, SeriesUpdate(status="cancelled"))
    row = recurring.update(db, household.id, series.id, SeriesUpdate(status="active"))
    assert row.cancelled_on is None


def test_editing_a_cancelled_series_keeps_the_original_day(db, household, series):
    series.status = SeriesStatus.cancelled
    series.cancelled_on = date(2026, 9, 20)
    db.commit()
    recurring.update(db, household.id, series.id, SeriesUpdate(notes="called support"))
    row = recurring.update(db, household.id, series.id, SeriesUpdate(status="cancelled"))
    assert row.cancelled_on == date(2026, 9, 20)


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def client(db, household):
    app.dependency_overrides[require_household] = lambda: household.id
    yield csrf_client(app, db, get_db)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_household, None)


def test_series_carries_cancel_help_and_cancelled_on(client, series):
    body = client.get("/recurring?status=all").json()[0]
    assert body["cancelled_on"] is None
    assert "netflix.com" in body["cancel_help"]["url"]
    assert body["cancel_help"]["via"] is None


def test_series_with_no_known_link_has_null_cancel_help(client, db, series):
    series.label = "Joe's Corner Gym"
    db.commit()
    assert client.get("/recurring?status=all").json()[0]["cancel_help"] is None


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "http://example.com/cancel", "data:text/html,x", "example.com"]
)
def test_patch_rejects_a_cancel_url_that_is_not_https(client, series, url):
    assert client.patch(f"/recurring/{series.id}", json={"cancel_url": url}).status_code == 422


def test_patch_accepts_https_and_clearing(client, series):
    r = client.patch(f"/recurring/{series.id}", json={"cancel_url": "https://example.com/cancel"})
    assert r.status_code == 200 and r.json()["cancel_url"] == "https://example.com/cancel"
    r = client.patch(f"/recurring/{series.id}", json={"cancel_url": None})
    assert r.status_code == 200 and r.json()["cancel_url"] is None


def test_patch_cancelled_returns_cancelled_on(client, series):
    r = client.patch(f"/recurring/{series.id}", json={"status": "cancelled"})
    assert r.json()["cancelled_on"] == _today().isoformat()
