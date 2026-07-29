import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.household import Household
from app.providers.llm import ClaudeProvider, LLMError
from app.schemas.account import AccountCreate
from app.schemas.transaction import TxnCreate
from app.services import accounts as accounts_service
from app.services import digest as digest_service
from app.services import insights
from app.services import recurring as recurring_service
from app.services import transactions as txn_service


class RecordingLLM:
    """Captures what the model would have been sent, and returns a canned answer."""

    name = "recording"
    model = "recording-1"

    def __init__(self) -> None:
        self.system = ""
        self.prompt = ""

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        self.system = system
        self.prompt = prompt
        return "## Where you stand\n- Fine."


def _household(db) -> uuid.UUID:
    h = Household(name="Insights Household")
    db.add(h)
    db.commit()
    return h.id


def _seed(db, hid):
    checking = accounts_service.create(
        db, hid, AccountCreate(type="checking", name="Checking", balance=Decimal(2000))
    )
    accounts_service.create(
        db, hid, AccountCreate(type="credit_card", name="Card", balance=Decimal(500))
    )
    now = datetime.now(UTC)
    for month in range(3):
        posted = now - timedelta(days=30 * month + 1)
        txn_service.create(
            db,
            hid,
            TxnCreate(
                account_id=checking.id,
                posted_at=posted,
                amount=Decimal(3000),
                merchant_raw="Payroll",
            ),
        )
        txn_service.create(
            db,
            hid,
            TxnCreate(
                account_id=checking.id,
                posted_at=posted,
                amount=Decimal("-15.99"),
                merchant_raw="Netflix",
            ),
        )
        txn_service.create(
            db,
            hid,
            TxnCreate(
                account_id=checking.id,
                posted_at=posted,
                amount=Decimal(-1200),
                merchant_raw="Rent",
            ),
        )
    return checking


def test_digest_computes_net_worth_from_accounts(db):
    hid = _household(db)
    _seed(db, hid)
    facts = digest_service.build(db, hid)
    assert facts.assets == 2000.0
    assert facts.debts == 500.0
    assert facts.net_worth == 1500.0


def test_digest_ranks_merchants_by_spend_and_ignores_income(db):
    hid = _household(db)
    _seed(db, hid)
    facts = digest_service.build(db, hid)
    assert facts.top_merchants[0].merchant == "Rent"
    assert facts.top_merchants[0].total == 3600.0
    assert "Payroll" not in [m.merchant for m in facts.top_merchants]


def test_digest_flags_a_repeating_charge_as_recurring(db):
    hid = _household(db)
    _seed(db, hid)
    recurring_service.detect(db, hid)
    facts = digest_service.build(db, hid)
    by_merchant = {r["merchant"]: r for r in facts.recurring_candidates}
    assert "Netflix" in by_merchant
    assert by_merchant["Netflix"]["cadence"] == "monthly"
    assert by_merchant["Netflix"]["next_expected_on"] is not None


def test_digest_separates_income_and_spending_per_month(db):
    hid = _household(db)
    _seed(db, hid)
    facts = digest_service.build(db, hid)
    assert len(facts.months) >= 3
    for month in facts.months:
        assert month.income == 3000.0
        assert month.spending == 1215.99


def test_the_model_is_given_the_real_numbers_and_told_not_to_invent_any(db):
    hid = _household(db)
    _seed(db, hid)
    llm = RecordingLLM()

    result = insights.generate(db, hid, provider=llm)

    assert result["summary"].startswith("## Where you stand")
    assert result["model"] == "recording-1"
    # The prompt carries the computed digest, not raw rows for the model to add up.
    payload = json.loads(llm.prompt.split("```json")[1].split("```")[0])
    assert payload["net_worth"] == 1500.0
    assert "must come from" in llm.prompt
    assert "Never estimate" in llm.system


def test_a_users_question_is_passed_through(db):
    hid = _household(db)
    _seed(db, hid)
    llm = RecordingLLM()
    insights.generate(db, hid, provider=llm, question="Can I afford a $900 flight?")
    assert "Can I afford a $900 flight?" in llm.prompt


def test_empty_household_says_so_without_calling_the_model(db):
    hid = _household(db)
    llm = RecordingLLM()
    result = insights.generate(db, hid, provider=llm)
    assert "Nothing to analyze yet" in result["summary"]
    assert llm.prompt == ""  # no API call, no spend


def test_claude_provider_without_a_key_reports_unavailable():
    provider = ClaudeProvider(api_key="")
    assert provider.configured is False
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        provider.complete("system", "prompt")
