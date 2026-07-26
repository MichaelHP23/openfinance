import json
import uuid

from sqlalchemy.orm import Session

from app.providers.llm import ClaudeProvider, LLMError, LLMProvider
from app.services import digest as digest_service

SYSTEM = """You are a blunt, competent financial analyst reviewing one household's own data.

Absolute rules:
- Every figure you cite MUST come from the JSON you are given. Never estimate, never
  extrapolate, never invent a number. If the data doesn't support a claim, say so.
- If the data is thin (few transactions, no history), say that plainly instead of
  padding with generic advice.
- Do not recommend specific financial products, investments, or tax strategies.

Write for someone looking at their own dashboard. Be specific and concrete: name the
merchants, quote the amounts, point at the months. Skip pleasantries and disclaimers.

Format your answer as markdown with these sections, each 1-3 short bullets:

## Where you stand
## What changed
## Worth a look

Keep the whole thing under 250 words."""


def generate(
    db: Session,
    household_id: uuid.UUID,
    provider: LLMProvider | None = None,
    question: str | None = None,
) -> dict[str, str]:
    facts = digest_service.build(db, household_id).to_dict()

    if facts["transaction_count"] == 0 and not facts["accounts"]:
        return {
            "summary": "Nothing to analyze yet — add an account and some transactions first.",
            "model": "none",
        }

    prompt = (
        "Here is the household's financial data as JSON. Every number in your response "
        "must come from it.\n\n```json\n" + json.dumps(facts, indent=2, default=str) + "\n```\n"
    )
    if question:
        prompt += f"\nThe user asks specifically: {question}\n"

    llm = provider or ClaudeProvider()
    summary = llm.complete(SYSTEM, prompt)
    return {"summary": summary, "model": getattr(llm, "model", llm.name)}


__all__ = ["LLMError", "generate"]
