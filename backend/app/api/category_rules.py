import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.category_rule import CategoryRule
from app.providers.llm import ClaudeProvider, LLMError
from app.schemas.category import (
    BackfillIn,
    ReorderIn,
    RuleCreate,
    RuleOut,
    RuleUpdate,
    SuggestResponse,
    UncategorizedOut,
)
from app.services import categorization

router = APIRouter(tags=["categorization"])


@router.get("/category-rules", response_model=list[RuleOut])
def list_rules(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[CategoryRule]:
    return categorization.rules_for(db, hid)


@router.post("/category-rules", response_model=RuleOut)
def create_rule(
    body: RuleCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryRule:
    try:
        return categorization.create_rule(db, hid, body)
    except (categorization.BadPattern, categorization.UnknownCategory) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/category-rules/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryRule:
    try:
        row = categorization.update_rule(db, hid, rule_id, body)
    except (categorization.BadPattern, categorization.UnknownCategory) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return row


@router.delete("/category-rules/{rule_id}")
def delete_rule(
    rule_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not categorization.delete_rule(db, hid, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "ok"}


@router.post("/category-rules/reorder")
def reorder_rules(
    body: ReorderIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"reordered": categorization.reorder(db, hid, body.rule_ids)}


@router.post("/category-rules/preview")
def preview_rule(
    body: RuleCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    try:
        return {"matches": categorization.preview(db, hid, body)}
    except categorization.BadPattern as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/categorization/backfill")
def run_backfill(
    body: BackfillIn,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {
        "changed": categorization.backfill(
            db, hid, only_uncategorized=body.only_uncategorized
        )
    }


@router.get("/categorization/uncategorized", response_model=list[UncategorizedOut])
def list_uncategorized(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[UncategorizedOut]:
    return [
        UncategorizedOut(
            merchant=m.merchant, count=m.count, total=m.total, currency=m.currency
        )
        for m in categorization.uncategorized_merchants(db, hid)
    ]


@router.post("/categories/suggest", response_model=SuggestResponse)
def suggest(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> SuggestResponse:
    """Proposals only. Confirming one is a normal POST /category-rules by the client."""
    provider = ClaudeProvider()
    if not provider.configured:
        raise HTTPException(status_code=503, detail="No ANTHROPIC_API_KEY configured")
    try:
        suggestions, model = categorization.suggest_rules(db, hid, provider)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SuggestResponse(suggestions=suggestions, model=model)
