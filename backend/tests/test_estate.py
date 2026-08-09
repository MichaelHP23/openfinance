import pytest

from app.models.account import Account, AccountType
from app.models.document import Document, DocumentKind
from app.models.household import Household
from app.services import estate


@pytest.fixture
def household(db):
    row = Household(name="Estate Household")
    db.add(row)
    db.commit()
    return row


def test_checklist_reports_every_gap_when_nothing_is_set_up(db, household):
    db.add(Account(household_id=household.id, type=AccountType.investment, name="401k", currency="USD"))
    db.commit()

    result = estate.checklist(db, household.id)

    by_label = {i.label: i for i in result.items}
    assert by_label["Will on file"].satisfied is False
    assert by_label["Beneficiary on every retirement/insurance account"].satisfied is False
    assert result.gaps >= 2


def test_checklist_is_satisfied_once_a_will_and_beneficiaries_are_on_file(db, household):
    acct = Account(
        household_id=household.id, type=AccountType.investment, name="401k", currency="USD",
        beneficiary="Jane Doe",
    )
    db.add(acct)
    db.add(
        Document(
            household_id=household.id, kind=DocumentKind.will, title="Will", filename="w.pdf",
            content_type="application/pdf", size_bytes=1, ciphertext_path="/tmp/w.enc",
        )
    )
    db.commit()

    result = estate.checklist(db, household.id)
    by_label = {i.label: i for i in result.items}
    assert by_label["Will on file"].satisfied is True
    assert by_label["Beneficiary on every retirement/insurance account"].satisfied is True


def test_checklist_flags_a_missing_beneficiary_on_one_of_several_accounts(db, household):
    db.add_all(
        [
            Account(household_id=household.id, type=AccountType.investment, name="IRA",
                    currency="USD", beneficiary="Jane Doe"),
            Account(household_id=household.id, type=AccountType.investment, name="401k",
                    currency="USD", beneficiary=None),
        ]
    )
    db.commit()

    result = estate.checklist(db, household.id)
    item = next(i for i in result.items if i.label == "Beneficiary on every retirement/insurance account")
    assert item.satisfied is False
    assert "401k" in item.detail


def test_checklist_deed_check_compares_counts_of_property_accounts_to_deed_documents(db, household):
    db.add_all(
        [
            Account(household_id=household.id, type=AccountType.asset, name="Rental House", currency="USD"),
            Account(household_id=household.id, type=AccountType.asset, name="Cabin", currency="USD"),
        ]
    )
    db.commit()

    no_deeds = estate.checklist(db, household.id)
    deed_item = next(i for i in no_deeds.items if "Deed" in i.label)
    assert deed_item.satisfied is False

    db.add(
        Document(household_id=household.id, kind=DocumentKind.deed, title="Rental deed",
                 filename="d1.pdf", content_type="application/pdf", size_bytes=1, ciphertext_path="/tmp/d1.enc")
    )
    db.add(
        Document(household_id=household.id, kind=DocumentKind.title, title="Cabin title",
                 filename="d2.pdf", content_type="application/pdf", size_bytes=1, ciphertext_path="/tmp/d2.enc")
    )
    db.commit()

    now_satisfied = estate.checklist(db, household.id)
    deed_item = next(i for i in now_satisfied.items if "Deed" in i.label)
    assert deed_item.satisfied is True


def test_checklist_with_no_property_accounts_is_satisfied_by_default(db, household):
    result = estate.checklist(db, household.id)
    deed_item = next(i for i in result.items if "Deed" in i.label)
    assert deed_item.satisfied is True
