import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

Credentials = dict[str, Any]

from app.core.encryption import decrypt, encrypt
from app.models.connection import ProviderConnection


@dataclass
class AccountDTO:
    external_id: str
    name: str
    type: str
    currency: str
    balance: Decimal


@dataclass
class TxnDTO:
    external_id: str
    account_external_id: str
    posted_at: datetime
    amount: Decimal
    currency: str
    merchant_raw: str


class BankProvider(Protocol):
    name: str

    def link_account(
        self, household_id: uuid.UUID, credentials: Credentials
    ) -> ProviderConnection: ...
    def fetch_accounts(self, conn: ProviderConnection) -> list[AccountDTO]: ...
    def fetch_transactions(
        self, conn: ProviderConnection, since: datetime | None
    ) -> list[TxnDTO]: ...


def _context_aad(conn: ProviderConnection) -> bytes:
    # Binds ciphertext to the storage context (household + provider) so a blob
    # copied/swapped between rows fails to decrypt instead of decrypting silently.
    return f"{conn.household_id}:{conn.provider.value}".encode()


def set_credentials(conn: ProviderConnection, creds: Credentials) -> None:
    conn.encrypted_credentials = encrypt(json.dumps(creds).encode(), aad=_context_aad(conn))


def get_credentials(conn: ProviderConnection) -> Credentials:
    creds: Credentials = json.loads(
        decrypt(conn.encrypted_credentials, aad=_context_aad(conn)).decode()
    )
    return creds
