"""LLM provider seam.

Kept behind a Protocol like `BankProvider`, so the insights service depends on an
interface rather than on Anthropic specifically.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ProviderReply:
    """One turn of a tool-calling conversation. `stop_reason` is the Anthropic
    Messages API's own vocabulary ("tool_use", "end_turn", "max_tokens", ...) —
    app.services.insights.ask only ever checks it against "tool_use"."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str: ...

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1200,
    ) -> ProviderReply: ...


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        # `or` would let an explicit "" silently pick up the ambient key, so an
        # intentionally unconfigured provider could not be constructed.
        self.api_key = settings.anthropic_api_key if api_key is None else api_key
        self.model = model or settings.llm_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        if not self.configured:
            raise LLMError("No ANTHROPIC_API_KEY set")

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise LLMError("anthropic package is not installed") from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            message = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise LLMError(f"Claude request failed: {exc}") from exc

        parts = [
            block.text for block in message.content if isinstance(block, anthropic.types.TextBlock)
        ]
        return "".join(parts).strip()

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1200,
    ) -> ProviderReply:
        if not self.configured:
            raise LLMError("No ANTHROPIC_API_KEY set")

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise LLMError("anthropic package is not installed") from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            message = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise LLMError(f"Claude request failed: {exc}") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in message.content:
            if isinstance(block, anthropic.types.TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, anthropic.types.ToolUseBlock):
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))

        return ProviderReply(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=message.stop_reason or "end_turn",
        )
