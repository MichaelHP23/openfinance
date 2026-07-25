import uuid
from datetime import datetime

from app.models.connection import Provider, ProviderConnection
from app.providers.base import AccountDTO, Credentials, TxnDTO, set_credentials


class ManualProvider:
    name = "manual"

    def link_account(self, household_id: uuid.UUID, credentials: Credentials) -> ProviderConnection:
        conn = ProviderConnection(household_id=household_id, provider=Provider.manual)
        set_credentials(conn, credentials or {"kind": "manual"})
        return conn

    def fetch_accounts(self, conn: ProviderConnection) -> list[AccountDTO]:
        return []  # manual accounts are user-created, not fetched

    def fetch_transactions(self, conn: ProviderConnection, since: datetime | None) -> list[TxnDTO]:
        return []
