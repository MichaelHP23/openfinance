import uuid

from app.providers.base import BankProvider, get_credentials
from app.providers.manual import ManualProvider


def test_manual_provider_satisfies_protocol():
    p: BankProvider = ManualProvider()  # type: ignore[assignment]
    assert p.name == "manual"


def test_link_account_encrypts_and_roundtrips():
    conn = ManualProvider().link_account(uuid.uuid4(), {"secret": "abc"})
    assert conn.encrypted_credentials != b'{"secret": "abc"}'
    assert get_credentials(conn) == {"secret": "abc"}
