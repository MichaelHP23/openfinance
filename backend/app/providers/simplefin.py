"""SimpleFIN Bridge provider.

The protocol is deliberately small: you claim a one-time setup token to get a durable
access URL (credentials embedded in it), then GET `<access_url>/accounts` for accounts
and their transactions as JSON. Read-only by design — there is no write surface.

https://www.simplefin.org/protocol.html
"""

import base64
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.models.connection import Provider, ProviderConnection
from app.providers.base import AccountDTO, Credentials, TxnDTO, get_credentials, set_credentials

TIMEOUT = 30.0


class SimpleFinError(Exception):
    pass


def _decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise SimpleFinError(f"Non-numeric {field}: {value!r}") from exc


def _currency(raw: object) -> str:
    # SimpleFIN allows a URL here for non-ISO currencies (e.g. crypto). Anything that
    # isn't a 3-letter code is not something this app can handle yet.
    code = str(raw or "USD")
    return code.upper() if len(code) == 3 else "USD"


# ponytail: SimpleFIN carries no account-type field, so this reads the name the bank
# gave us. Wrong guesses are cosmetic — type only affects the asset/liability split.
_TYPE_HINTS = (
    ("credit_card", ("credit card", "creditcard", "card", "visa", "mastercard", "amex")),
    ("savings", ("saving", "money market", "cd ", "certificate")),
    ("investment", ("invest", "brokerage", "401", "ira", "roth", "retirement")),
    ("loan", ("loan", "mortgage", "student", "auto financing")),
)


def guess_account_type(name: str, org: str = "") -> str:
    haystack = f"{name} {org}".lower()
    for account_type, hints in _TYPE_HINTS:
        if any(h in haystack for h in hints):
            return account_type
    return "checking"


class SimpleFinProvider:
    name = "simplefin"

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Injectable so tests can drive it with a MockTransport instead of the network.
        self._client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    # --- linking -------------------------------------------------------------

    @staticmethod
    def is_demo_token(setup_token: str) -> bool:
        """SimpleFIN's published demo token returns invented accounts, not a real bank.

        Easy to grab by mistake from the docs, and the resulting data looks plausible
        enough to be confusing, so it is worth naming explicitly.
        """
        try:
            url = base64.b64decode(setup_token.strip(), validate=True).decode()
        except Exception:  # noqa: BLE001 - unparseable means "not the demo", claim() reports why
            return False
        return url.rstrip("/").endswith("/claim/demo")

    def claim(self, setup_token: str) -> str:
        """Exchange a one-time setup token for a durable access URL."""
        try:
            claim_url = base64.b64decode(setup_token.strip(), validate=True).decode()
        except Exception as exc:
            raise SimpleFinError("Setup token is not valid base64") from exc

        if not claim_url.startswith("https://"):
            raise SimpleFinError("Setup token must decode to an https URL")

        resp = self._client.post(claim_url)
        if resp.status_code != 200:
            raise SimpleFinError(
                f"Claiming the setup token failed ({resp.status_code}). "
                "Setup tokens are single-use — generate a fresh one."
            )

        access_url = resp.text.strip()
        if not access_url.startswith("https://"):
            raise SimpleFinError("Bridge did not return an access URL")
        return access_url

    def link_account(self, household_id: uuid.UUID, credentials: Credentials) -> ProviderConnection:
        token = str(credentials.get("setup_token", "")).strip()
        if not token:
            raise SimpleFinError("A setup token is required")

        conn = ProviderConnection(household_id=household_id, provider=Provider.simplefin)
        set_credentials(conn, {"access_url": self.claim(token), "demo": self.is_demo_token(token)})
        return conn

    # --- fetching ------------------------------------------------------------

    def _get(self, conn: ProviderConnection, since: datetime | None) -> dict[str, Any]:
        access_url = get_credentials(conn).get("access_url")
        if not access_url:
            raise SimpleFinError("Connection has no access URL")

        params: dict[str, int] = {}
        if since is not None:
            params["start-date"] = int(since.timestamp())

        resp = self._client.get(f"{access_url.rstrip('/')}/accounts", params=params)
        if resp.status_code == 403:
            raise SimpleFinError("Access URL was rejected — the connection may need re-linking")
        if resp.status_code != 200:
            raise SimpleFinError(f"SimpleFIN returned {resp.status_code}")

        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise SimpleFinError("SimpleFIN returned a non-JSON body") from exc

        # `errors` reports per-institution problems while other accounts still return
        # fine, so it's only fatal when nothing came back at all.
        errors = data.get("errors") or []
        if errors and not data.get("accounts"):
            raise SimpleFinError("; ".join(str(e) for e in errors))
        return data

    def fetch_accounts(self, conn: ProviderConnection) -> list[AccountDTO]:
        data = self._get(conn, since=None)
        return [
            AccountDTO(
                external_id=str(a["id"]),
                name=str(a.get("name") or "Account"),
                type=guess_account_type(
                    str(a.get("name") or ""), str((a.get("org") or {}).get("name") or "")
                ),
                currency=_currency(a.get("currency")),
                balance=_decimal(a.get("balance", "0"), "balance"),
            )
            for a in data.get("accounts", [])
        ]

    def fetch_transactions(self, conn: ProviderConnection, since: datetime | None) -> list[TxnDTO]:
        data = self._get(conn, since=since)
        out: list[TxnDTO] = []
        for account in data.get("accounts", []):
            currency = _currency(account.get("currency"))
            for t in account.get("transactions") or []:
                out.append(
                    TxnDTO(
                        external_id=str(t["id"]),
                        account_external_id=str(account["id"]),
                        posted_at=datetime.fromtimestamp(int(t["posted"]), UTC),
                        amount=_decimal(t.get("amount", "0"), "amount"),
                        currency=currency,
                        # `payee` is the cleaned name when the bank supplies one.
                        merchant_raw=str(t.get("payee") or t.get("description") or "Unknown"),
                    )
                )
        return out

    def institution_names(self, conn: ProviderConnection) -> dict[str, str]:
        """external account id → institution name, for labelling imported accounts."""
        data = self._get(conn, since=None)
        return {
            str(a["id"]): str((a.get("org") or {}).get("name") or "")
            for a in data.get("accounts", [])
        }
