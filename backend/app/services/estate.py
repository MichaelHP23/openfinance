"""Estate readiness checklist — a computed read, no storage of its own. It reports
gaps against three questions Origin's "estate planning" pillar asks: is there a will
on file, does every retirement/insurance account carry a beneficiary, is there a deed
for every property account. It never drafts a will or a beneficiary form — that's
explicitly cut (design spec, P5) — it only reports what's missing.

`AccountType` (models/account.py) has nine values and none of them is `retirement`,
`insurance`, or `property` — the closest fits are `investment` (something that names
a beneficiary) and `asset` (something a deed attaches to). Both choices are named
here, not silently assumed; see this plan's recorded deviations for the reasoning.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account, AccountType
from app.models.document import Document, DocumentKind


@dataclass
class ChecklistItem:
    label: str
    satisfied: bool
    detail: str


@dataclass
class Checklist:
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def gaps(self) -> int:
        return sum(1 for i in self.items if not i.satisfied)


def checklist(db: Session, household_id: uuid.UUID) -> Checklist:
    items: list[ChecklistItem] = []

    has_will = (
        db.scalar(
            select(Document.id).where(Document.household_id == household_id, Document.kind == DocumentKind.will)
        )
        is not None
    )
    items.append(
        ChecklistItem(
            label="Will on file",
            satisfied=has_will,
            detail="Uploaded to the vault." if has_will else "No will uploaded to the vault yet.",
        )
    )

    retirement_accounts = list(
        db.scalars(
            select(Account).where(Account.household_id == household_id, Account.type == AccountType.investment)
        )
    )
    missing_beneficiary = [a for a in retirement_accounts if not a.beneficiary]
    items.append(
        ChecklistItem(
            label="Beneficiary on every retirement/insurance account",
            satisfied=len(missing_beneficiary) == 0,
            detail=(
                "All set." if not missing_beneficiary
                else f"Missing on: {', '.join(a.name for a in missing_beneficiary)}"
            ),
        )
    )

    property_accounts = list(
        db.scalars(select(Account).where(Account.household_id == household_id, Account.type == AccountType.asset))
    )
    # No account_id on `documents` (the spec's own schema doesn't add one), so this can
    # only compare counts, not confirm which specific property a deed belongs to — see
    # this plan's recorded deviation.
    deed_count = len(
        list(
            db.scalars(
                select(Document).where(
                    Document.household_id == household_id,
                    Document.kind.in_([DocumentKind.deed, DocumentKind.title]),
                )
            )
        )
    )
    deed_satisfied = not property_accounts or deed_count >= len(property_accounts)
    items.append(
        ChecklistItem(
            label="Deed on file for every property account",
            satisfied=deed_satisfied,
            detail=(
                "No property accounts to check." if not property_accounts
                else "All set." if deed_satisfied
                else f"{deed_count} deed/title document(s) on file for {len(property_accounts)} property account(s)."
            ),
        )
    )

    return Checklist(items=items)
