import time
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.document import Document, DocumentKind
from app.models.household import Household
from app.services import documents


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


@pytest.fixture
def other_household(db):
    row = Household(name="Other Vault Household")
    db.add(row)
    db.commit()
    return row


@pytest.fixture(autouse=True)
def _isolated_documents_dir(tmp_path, monkeypatch):
    # Every test in this file gets its own throwaway directory — never the real
    # ./data/documents a running install would use.
    monkeypatch.setattr(settings, "documents_dir", str(tmp_path))


def test_upload_download_round_trip_is_byte_identical(db, household):
    plaintext = b"this is the whole will, byte for byte"
    doc = documents.save(
        db, household.id, kind=DocumentKind.will, title="My Will", filename="will.txt",
        content_type="text/plain", data=plaintext,
    )

    recovered = documents.read_plaintext(db, household.id, doc.id)
    assert recovered == plaintext


def test_ciphertext_on_disk_is_not_the_plaintext(db, household):
    plaintext = b"a secret only the household should ever read in the clear"
    doc = documents.save(
        db, household.id, kind=DocumentKind.other, title="Secret", filename="s.txt",
        content_type="text/plain", data=plaintext,
    )

    raw = Path(doc.ciphertext_path).read_bytes()
    assert raw != plaintext
    assert plaintext not in raw


def test_a_document_from_another_household_is_not_reachable(db, household, other_household):
    doc = documents.save(
        db, household.id, kind=DocumentKind.will, title="My Will", filename="w.txt",
        content_type="text/plain", data=b"private",
    )

    assert documents.get(db, other_household.id, doc.id) is None
    with pytest.raises(documents.DocumentNotFound):
        documents.read_plaintext(db, other_household.id, doc.id)


def test_list_for_is_scoped_and_newest_first(db, household):
    first = documents.save(db, household.id, kind=DocumentKind.other, title="First",
                            filename="a.txt", content_type="text/plain", data=b"a")
    # `documents.save()` stamps `created_at` from the application clock (see
    # documents.py) specifically so this ordering is real even when both saves land
    # in the same DB transaction, as they do under the `db` test fixture — Postgres's
    # `now()` is fixed for a whole transaction, so two saves sharing one would
    # otherwise tie. The sleep is just extra margin against clock-resolution flakes.
    time.sleep(0.02)
    second = documents.save(db, household.id, kind=DocumentKind.other, title="Second",
                             filename="b.txt", content_type="text/plain", data=b"b")

    rows = documents.list_for(db, household.id)
    assert [r.id for r in rows] == [second.id, first.id]


def test_delete_removes_the_row_and_the_file(db, household):
    doc = documents.save(db, household.id, kind=DocumentKind.other, title="Gone",
                          filename="g.txt", content_type="text/plain", data=b"x")
    path = Path(doc.ciphertext_path)
    assert path.exists()

    assert documents.delete(db, household.id, doc.id) is True
    assert documents.get(db, household.id, doc.id) is None
    assert not path.exists()


def test_delete_of_unknown_document_returns_false(db, household):
    assert documents.delete(db, household.id, uuid.uuid4()) is False
