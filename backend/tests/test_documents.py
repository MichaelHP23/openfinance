import pytest

from app.models.document import Document, DocumentKind
from app.models.household import Household


@pytest.fixture
def household(db):
    row = Household(name="Vault Household")
    db.add(row)
    db.commit()
    return row


def test_document_round_trips_every_column(db, household):
    doc = Document(
        household_id=household.id,
        kind=DocumentKind.will,
        title="My Will",
        filename="will.pdf",
        content_type="application/pdf",
        size_bytes=1234,
        ciphertext_path="/data/documents/x/y.enc",
        notes="Signed 2026",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    fetched = db.get(Document, doc.id)
    assert fetched is not None
    assert fetched.kind == DocumentKind.will
    assert fetched.title == "My Will"
    assert fetched.filename == "will.pdf"
    assert fetched.content_type == "application/pdf"
    assert fetched.size_bytes == 1234
    assert fetched.ciphertext_path == "/data/documents/x/y.enc"
    assert fetched.notes == "Signed 2026"
    assert fetched.created_at is not None


def test_document_notes_is_optional(db, household):
    doc = Document(
        household_id=household.id, kind=DocumentKind.other, title="Misc", filename="x.txt",
        content_type="text/plain", size_bytes=1, ciphertext_path="/tmp/x.enc",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    assert doc.notes is None
