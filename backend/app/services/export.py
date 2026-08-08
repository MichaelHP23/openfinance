"""Every table this household owns, one CSV per table, zipped. Enumerates tables from
`Base.metadata` at runtime rather than a hand-maintained list, so a new model with a
`household_id` column is a fact `test_export.py` can catch rather than a step someone
has to remember to add here.

`users.password_hash` and `provider_connections.encrypted_credentials` both carry a
`household_id` column and would otherwise qualify, but they're credential material,
not financial data — see this plan's recorded deviation for the reasoning.
"""

import csv
import io
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from app.models.base import Base

EXCLUDED_TABLES = {"users", "provider_connections"}


def _household_tables() -> list[Table]:
    return sorted(
        (t for name, t in Base.metadata.tables.items() if "household_id" in t.columns and name not in EXCLUDED_TABLES),
        key=lambda t: t.name,
    )


def _serialize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (Decimal, date, datetime, uuid.UUID)):
        return str(value)
    if hasattr(value, "value"):  # str-backed Enum members
        return str(value.value)
    return str(value)


def build_zip(db: Session, household_id: uuid.UUID) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in _household_tables():
            hid_col = table.c.household_id
            # `is_(None)` matches `categories`' system rows (household_id IS NULL) so a
            # household's export includes the shared taxonomy its own transactions
            # reference by id. Every other table's household_id is NOT NULL at the
            # database level, so this clause is a no-op for all of them.
            rows = db.execute(select(table).where((hid_col == household_id) | hid_col.is_(None))).all()
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow([c.name for c in table.columns])
            for row in rows:
                writer.writerow([_serialize(v) for v in row])
            zf.writestr(f"{table.name}.csv", out.getvalue())
    return buf.getvalue()
