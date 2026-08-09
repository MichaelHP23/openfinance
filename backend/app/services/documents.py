"""The document vault. Files are encrypted with the same AES-GCM envelope provider
credentials use (`app/core/encryption.py`, `app/providers/base.py`) — read into
memory, sealed once with `encrypt()`, written to disk as one opaque blob under
`settings.documents_dir/<household_id>/<document_id>.enc`. Plaintext exists only for
the duration of an upload or a download, never on disk.

ponytail: whole-file encrypt/decrypt, no streaming/chunked AEAD — a will or an
insurance PDF is a few megabytes, well within what the provider-credentials blob
already proves out. Move to chunked AEAD if uploads ever need to cover something
video-sized.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.encryption import decrypt, encrypt
from app.models.document import Document, DocumentKind


class DocumentNotFound(Exception):
    """A document id that doesn't resolve for this household — missing, or another
    household's row. The router turns this into a 404, never a 500."""


def _aad(household_id: uuid.UUID, document_id: uuid.UUID) -> bytes:
    # Bound to the document's own id, not just the household — swapping one
    # document's ciphertext onto another row in the same household still fails to
    # decrypt, the same defense-in-depth `providers/base.py::_context_aad` gives a
    # provider connection.
    return f"{household_id}:document:{document_id}".encode()


def _path_for(household_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    directory = Path(settings.documents_dir) / str(household_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{document_id}.enc"


def save(
    db: Session,
    household_id: uuid.UUID,
    *,
    kind: DocumentKind,
    title: str,
    filename: str,
    content_type: str,
    data: bytes,
    notes: str | None = None,
) -> Document:
    doc = Document(
        household_id=household_id, kind=kind, title=title, filename=filename,
        content_type=content_type, size_bytes=len(data), ciphertext_path="", notes=notes,
        # Stamped here rather than left to the column's server_default: `created_at`'s
        # server_default is `func.now()`, which is the *transaction's* start time in
        # Postgres, not per-statement — every row inserted by calls sharing one
        # transaction gets the identical value. `list_for`'s "newest first" ordering
        # needs real per-row separation, and the application clock gives it that.
        created_at=datetime.now(UTC),
    )
    db.add(doc)
    db.flush()  # assigns doc.id (UUIDMixin's client-side default) without committing —
    # the AAD binds to that id, so the id has to exist before the file is sealed.

    path = _path_for(household_id, doc.id)
    path.write_bytes(encrypt(data, aad=_aad(household_id, doc.id)))
    doc.ciphertext_path = str(path)

    db.commit()
    db.refresh(doc)
    return doc


def get(db: Session, household_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    return db.scalar(
        select(Document).where(Document.id == document_id, Document.household_id == household_id)
    )


def list_for(db: Session, household_id: uuid.UUID) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(Document.household_id == household_id).order_by(Document.created_at.desc())
        )
    )


def read_plaintext(db: Session, household_id: uuid.UUID, document_id: uuid.UUID) -> bytes:
    """Decrypt for a download. Raises DocumentNotFound for a missing id or a foreign
    household's — the same row a caller couldn't `get()` either."""
    doc = get(db, household_id, document_id)
    if doc is None:
        raise DocumentNotFound(str(document_id))
    blob = Path(doc.ciphertext_path).read_bytes()
    return decrypt(blob, aad=_aad(household_id, doc.id))


def delete(db: Session, household_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    doc = get(db, household_id, document_id)
    if doc is None:
        return False
    Path(doc.ciphertext_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return True
