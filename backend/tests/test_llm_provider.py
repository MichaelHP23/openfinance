"""ClaudeProvider.complete_with_tools — the seam app.services.insights.ask calls on
every turn of the tool-calling loop. Only the unconfigured-provider path is unit
tested here, matching the existing precedent for .complete() in
test_insights.py::test_claude_provider_without_a_key_reports_unavailable: a real call
needs network access this suite doesn't have, and every other test in this plan
drives the loop through a fake provider that implements the Protocol directly rather
than mocking the anthropic SDK client."""

import pytest

from app.providers.llm import ClaudeProvider, LLMError, ProviderReply, ToolCall


def test_complete_with_tools_without_a_key_reports_unavailable():
    provider = ClaudeProvider(api_key="")
    assert provider.configured is False
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        provider.complete_with_tools("system", [{"role": "user", "content": "hi"}], [])


def test_provider_reply_defaults_to_no_tool_calls_and_end_turn():
    reply = ProviderReply(text="hello")
    assert reply.tool_calls == []
    assert reply.stop_reason == "end_turn"


def test_tool_call_carries_its_id_name_and_input():
    call = ToolCall(id="t1", name="net_worth_history", input={"months": 3})
    assert call.id == "t1"
    assert call.name == "net_worth_history"
    assert call.input == {"months": 3}
