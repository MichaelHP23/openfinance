import base64
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.providers.base import get_credentials
from app.providers.simplefin import SimpleFinError, SimpleFinProvider, guess_account_type

ACCESS_URL = "https://user:pass@bridge.simplefin.org/simplefin"
SETUP_TOKEN = base64.b64encode(b"https://bridge.simplefin.org/simplefin/claim/abc").decode()

ACCOUNTS_BODY = {
    "errors": [],
    "accounts": [
        {
            "id": "acct-1",
            "name": "Everyday Checking",
            "currency": "USD",
            "balance": "1200.55",
            "org": {"name": "First Platypus Bank"},
            "transactions": [
                {"id": "t1", "posted": 1767225600, "amount": "-9.99", "description": "COFFEE"},
                {
                    "id": "t2",
                    "posted": 1767312000,
                    "amount": "2500.00",
                    "description": "ACH CREDIT",
                    "payee": "Payroll",
                },
            ],
        },
        {
            "id": "acct-2",
            "name": "Sapphire Credit Card",
            "currency": "USD",
            "balance": "-430.10",
            "org": {"name": "First Platypus Bank"},
            "transactions": [],
        },
    ],
}


def provider_with(handler) -> SimpleFinProvider:
    return SimpleFinProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def accounts_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        return httpx.Response(200, text=ACCESS_URL)
    return httpx.Response(200, json=ACCOUNTS_BODY)


def test_claim_exchanges_setup_token_for_access_url():
    assert provider_with(accounts_handler).claim(SETUP_TOKEN) == ACCESS_URL


def test_claim_rejects_a_non_base64_token():
    with pytest.raises(SimpleFinError, match="base64"):
        provider_with(accounts_handler).claim("not-a-token!!")


def test_claim_rejects_a_token_pointing_somewhere_other_than_https():
    token = base64.b64encode(b"http://insecure.example.com/claim").decode()
    with pytest.raises(SimpleFinError, match="https"):
        provider_with(accounts_handler).claim(token)


def test_claim_reports_a_reused_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with pytest.raises(SimpleFinError, match="single-use"):
        provider_with(handler).claim(SETUP_TOKEN)


def test_link_account_stores_the_access_url_encrypted():
    conn = provider_with(accounts_handler).link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    assert ACCESS_URL.encode() not in conn.encrypted_credentials
    assert get_credentials(conn) == {"access_url": ACCESS_URL}


def test_link_account_requires_a_token():
    with pytest.raises(SimpleFinError, match="required"):
        provider_with(accounts_handler).link_account(uuid.uuid4(), {})


def _linked() -> tuple[SimpleFinProvider, object]:
    p = provider_with(accounts_handler)
    return p, p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})


def test_fetch_accounts_maps_balance_currency_and_guessed_type():
    p, conn = _linked()
    accounts = p.fetch_accounts(conn)
    assert [a.external_id for a in accounts] == ["acct-1", "acct-2"]
    assert accounts[0].balance == Decimal("1200.55")
    assert accounts[0].type == "checking"
    assert accounts[1].type == "credit_card"
    assert accounts[1].balance == Decimal("-430.10")


def test_fetch_transactions_prefers_payee_and_converts_unix_time():
    p, conn = _linked()
    txns = p.fetch_transactions(conn, since=None)
    assert [t.external_id for t in txns] == ["t1", "t2"]
    assert txns[0].merchant_raw == "COFFEE"
    assert txns[1].merchant_raw == "Payroll"  # payee wins over description
    assert txns[0].amount == Decimal("-9.99")
    assert txns[0].posted_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert txns[0].account_external_id == "acct-1"


def test_since_is_sent_as_a_unix_start_date():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=ACCESS_URL)
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=ACCOUNTS_BODY)

    p = provider_with(handler)
    conn = p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    p.fetch_transactions(conn, since=datetime(2026, 1, 1, tzinfo=UTC))
    assert seen["start-date"] == "1767225600"


def test_a_rejected_access_url_says_so():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=ACCESS_URL)
        return httpx.Response(403, text="nope")

    p = provider_with(handler)
    conn = p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    with pytest.raises(SimpleFinError, match="re-linking"):
        p.fetch_accounts(conn)


def test_errors_are_fatal_only_when_no_accounts_came_back():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=ACCESS_URL)
        return httpx.Response(200, json={"errors": ["Bank unavailable"], "accounts": []})

    p = provider_with(handler)
    conn = p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    with pytest.raises(SimpleFinError, match="Bank unavailable"):
        p.fetch_accounts(conn)


def test_partial_failure_still_returns_the_accounts_that_worked():
    body = {"errors": ["Bank B unavailable"], "accounts": ACCOUNTS_BODY["accounts"][:1]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=ACCESS_URL)
        return httpx.Response(200, json=body)

    p = provider_with(handler)
    conn = p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    assert len(p.fetch_accounts(conn)) == 1


def test_non_numeric_balance_is_rejected_rather_than_silently_zeroed():
    body = {"errors": [], "accounts": [{"id": "x", "name": "X", "balance": "unknown"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=ACCESS_URL)
        return httpx.Response(200, json=body)

    p = provider_with(handler)
    conn = p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    with pytest.raises(SimpleFinError, match="balance"):
        p.fetch_accounts(conn)


def test_non_json_body_is_reported_clearly():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=ACCESS_URL)
        return httpx.Response(200, text="<html>maintenance</html>")

    p = provider_with(handler)
    conn = p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    with pytest.raises(SimpleFinError, match="non-JSON"):
        p.fetch_accounts(conn)


def test_non_iso_currency_falls_back_to_usd():
    body = json.loads(json.dumps(ACCOUNTS_BODY))
    body["accounts"][0]["currency"] = "http://example.com/currency/doge"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=ACCESS_URL)
        return httpx.Response(200, json=body)

    p = provider_with(handler)
    conn = p.link_account(uuid.uuid4(), {"setup_token": SETUP_TOKEN})
    assert p.fetch_accounts(conn)[0].currency == "USD"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Sapphire Credit Card", "credit_card"),
        ("Platinum Visa", "credit_card"),
        ("High Yield Savings", "savings"),
        ("Roth IRA", "investment"),
        ("Brokerage Account", "investment"),
        ("Auto Loan", "loan"),
        ("Mortgage", "loan"),
        ("Everyday Checking", "checking"),
        ("Something Unlabelled", "checking"),
    ],
)
def test_account_type_guessing(name, expected):
    assert guess_account_type(name) == expected
