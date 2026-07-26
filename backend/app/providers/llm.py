"""LLM provider seam.

Kept behind a Protocol like `BankProvider`, so the insights service depends on an
interface rather than on Anthropic specifically.
"""

from typing import Protocol

from app.core.config import settings


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str: ...


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
