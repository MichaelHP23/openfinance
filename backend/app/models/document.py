import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DocumentKind(str, enum.Enum):
    will = "will"
    trust = "trust"
    insurance = "insurance"
    deed = "deed"
    title = "title"  # type: ignore[assignment]  # shadows str.title, same as TradeType.split
    statement = "statement"
    other = "other"


class Document(Base, UUIDMixin, TimestampMixin):
    """Metadata for one encrypted file in the household's vault.

    The file itself never touches this row or this database — only its encrypted
    bytes on disk do. `ciphertext_path` names a file under `settings.documents_dir`
    holding exactly the blob `app.core.encryption.encrypt()` returns: a wrapped DEK
    and the AES-GCM-sealed file body, the same envelope provider credentials use
    (`app/providers/base.py`). No separate `nonce`/`wrapped_key` columns — the real
    encryption module exposes one `encrypt`/`decrypt` pair over one opaque blob, not a
    lower-level API split into parts; see this plan's recorded deviation for why.
    """

    __tablename__ = "documents"

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(Enum(DocumentKind, name="document_kind"))
    title: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    ciphertext_path: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
