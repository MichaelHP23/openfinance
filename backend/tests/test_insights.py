import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.models.household import Household
from app.providers.llm import ClaudeProvider, LLMError, ProviderReply, ToolCall
from app.schemas.account import AccountCreate
from app.schemas.transaction import TxnCreate
from app.services import accounts as accounts_service
from app.services import digest as digest_service
from app.services import insights
from app.services import recurring as recurring_service
from app.services import transactions as txn_service


class ScriptedLLM:
    """A fake provider that plays back a fixed sequence of ProviderReply objects, so
    a test can drive the tool-calling loop through several turns without hitting a
    real model — the same role RecordingLLM played for the old single-call
    `generate`, widened for a multi-turn conversation."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, replies: list[ProviderReply]) -> None:
        self._replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        raise NotImplementedError("the advisor loop only calls complete_with_tools")

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1200,
    ) -> ProviderReply:
        self.calls.append([dict(m) for m in messages])
        return self._replies.pop(0)


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
    now = datetime.now(UTC).replace(day=15)
    for month in range(3):
        posted = now - timedelta(days=31 * month)
        txn_service.create(
            db, hid, TxnCreate(account_id=checking.id, posted_at=posted, amount=Decimal(3000), merchant_raw="Payroll")
        )
        txn_service.create(
            db, hid, TxnCreate(account_id=checking.id, posted_at=posted, amount=Decimal("-15.99"), merchant_raw="Netflix")
        )
        txn_service.create(
            db, hid, TxnCreate(account_id=checking.id, posted_at=posted, amount=Decimal(-1200), merchant_raw="Rent")
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


def test_digest_separates_income_and_spending_per_month(db):
    hid = _household(db)
    _seed(db, hid)
    facts = digest_service.build(db, hid)
    assert len(facts.months) >= 3
    for month in facts.months:
        assert month.income == 3000.0
        assert month.spending == 1215.99


def test_empty_household_says_so_without_calling_the_model(db):
    hid = _household(db)
    llm = ScriptedLLM([])
    result = insights.ask(db, hid, provider=llm)
    assert "Nothing to analyze yet" in result.answer
    assert result.trace == []
    assert llm.calls == []  # no API call, no spend


def test_ask_with_no_tool_call_just_answers_from_the_digest(db):
    hid = _household(db)
    _seed(db, hid)
    llm = ScriptedLLM([ProviderReply(text="## Where you stand\n- Fine.", stop_reason="end_turn")])
    result = insights.ask(db, hid, question="How am I doing?", provider=llm)
    assert result.answer == "## Where you stand\n- Fine."
    assert result.model == "scripted-1"
    assert result.trace == []
    # The opening message carries the computed digest, not raw rows for the model to
    # add up itself.
    opening = llm.calls[0][0]["content"]
    payload = json.loads(opening.split("```json")[1].split("```")[0])
    assert payload["net_worth"] == 1500.0
    assert "How am I doing?" in opening


def test_ask_with_no_question_uses_a_default_prompt(db):
    hid = _household(db)
    _seed(db, hid)
    llm = ScriptedLLM([ProviderReply(text="## Where you stand\n- Fine.", stop_reason="end_turn")])
    insights.ask(db, hid, provider=llm)
    assert "overview" in llm.calls[0][0]["content"].lower()


def test_ask_calls_a_tool_and_answers_from_its_result(db):
    hid = _household(db)
    _seed(db, hid)
    llm = ScriptedLLM(
        [
            ProviderReply(
                text="",
                tool_calls=[ToolCall(id="t1", name="net_worth_history", input={"months": 3})],
                stop_reason="tool_use",
            ),
            ProviderReply(text="## Where you stand\n- Net worth is healthy.", stop_reason="end_turn"),
        ]
    )
    result = insights.ask(db, hid, question="How's my net worth?", provider=llm)
    assert result.answer == "## Where you stand\n- Net worth is healthy."
    assert len(result.trace) == 1
    assert result.trace[0].tool == "net_worth_history"
    assert result.trace[0].args == {"months": 3}
    assert result.trace[0].result_summary  # not empty
    # The second call to the model includes the tool result as a tool_result block.
    second_call_messages = llm.calls[1]
    assert second_call_messages[-1]["content"][0]["type"] == "tool_result"
    assert second_call_messages[-1]["content"][0]["tool_use_id"] == "t1"


def test_ask_propagates_llm_error_when_the_provider_is_unconfigured(db):
    hid = _household(db)
    _seed(db, hid)
    provider = ClaudeProvider(api_key="")
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        insights.ask(db, hid, question="Anything?", provider=provider)


def test_claude_provider_without_a_key_reports_unavailable():
    provider = ClaudeProvider(api_key="")
    assert provider.configured is False
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        provider.complete("system", "prompt")


def test_ask_stops_at_the_tool_call_cap_with_a_note_not_an_error(db):
    hid = _household(db)
    _seed(db, hid)
    # The model keeps asking for another tool call forever; the loop must cut it off
    # at MAX_TOOL_CALLS rather than looping until the API bill notices.
    replies = [
        ProviderReply(
            text="",
            tool_calls=[ToolCall(id=f"t{i}", name="net_worth_history", input={"months": 1})],
            stop_reason="tool_use",
        )
        for i in range(insights.MAX_TOOL_CALLS + 3)
    ]
    llm = ScriptedLLM(replies)
    result = insights.ask(db, hid, question="?", provider=llm)
    assert len(result.trace) == insights.MAX_TOOL_CALLS
    assert "limit" in result.answer.lower()


def test_ask_stops_at_the_wall_clock_cap_with_a_note_not_an_error(db, monkeypatch):
    hid = _household(db)
    _seed(db, hid)
    # First call to time.monotonic() starts the clock; the second (inside the loop)
    # is already 200 seconds later — past the 120-second budget — so the loop must
    # return before ever calling the model.
    times = iter([0.0, 200.0])
    monkeypatch.setattr(insights.time, "monotonic", lambda: next(times))
    llm = ScriptedLLM(
        [ProviderReply(text="", tool_calls=[ToolCall(id="t1", name="net_worth_history", input={})], stop_reason="tool_use")]
    )
    result = insights.ask(db, hid, question="?", provider=llm)
    assert result.trace == []
    assert llm.calls == []
    assert "time" in result.answer.lower() or "budget" in result.answer.lower()


def test_a_tool_raising_does_not_kill_the_turn(db, monkeypatch):
    from app.services import advisor_tools

    hid = _household(db)
    _seed(db, hid)

    def boom(db, household_id, args):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        advisor_tools._REGISTRY, "net_worth_history", (advisor_tools.NetWorthHistoryArgs, boom)
    )
    llm = ScriptedLLM(
        [
            ProviderReply(
                text="",
                tool_calls=[ToolCall(id="t1", name="net_worth_history", input={"months": 1})],
                stop_reason="tool_use",
            ),
            ProviderReply(text="## Where you stand\n- Couldn't check that.", stop_reason="end_turn"),
        ]
    )
    result = insights.ask(db, hid, question="?", provider=llm)
    assert result.answer == "## Where you stand\n- Couldn't check that."
    assert "error" in result.trace[0].result_summary.lower()
    assert "boom" in result.trace[0].result_summary.lower()


def test_trace_has_exactly_one_entry_per_tool_call_the_model_actually_made(db):
    hid = _household(db)
    _seed(db, hid)
    llm = ScriptedLLM(
        [
            ProviderReply(
                text="",
                tool_calls=[
                    ToolCall(id="t1", name="net_worth_history", input={"months": 1}),
                    ToolCall(id="t2", name="holdings_summary", input={}),
                ],
                stop_reason="tool_use",
            ),
            ProviderReply(text="## Where you stand\n- Two things checked.", stop_reason="end_turn"),
        ]
    )
    result = insights.ask(db, hid, question="?", provider=llm)
    assert [t.tool for t in result.trace] == ["net_worth_history", "holdings_summary"]
