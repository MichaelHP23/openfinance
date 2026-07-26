import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.providers.llm import ClaudeProvider, LLMError
from app.services import digest as digest_service
from app.services import insights as insights_service
from app.services import snapshots as snapshots_service

router = APIRouter(tags=["insights"])


class InsightsOut(BaseModel):
    summary: str
    model: str


class AskIn(BaseModel):
    question: str | None = None


class NetWorthPointOut(BaseModel):
    on: str
    assets: float
    debts: float
    net: float


@router.get("/insights/available")
def insights_available() -> dict[str, bool]:
    """Lets the UI hide the assistant instead of offering a button that always fails."""
    return {"available": ClaudeProvider().configured}


@router.post("/insights", response_model=InsightsOut)
def generate_insights(
    body: AskIn | None = None,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> InsightsOut:
    try:
        result = insights_service.generate(db, hid, question=(body.question if body else None))
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return InsightsOut(**result)


@router.get("/insights/digest")
def digest(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """The exact facts the assistant is given — so its claims can be checked."""
    return digest_service.build(db, hid).to_dict()


@router.post("/snapshots")
def take_snapshot(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> dict[str, int]:
    return {"captured": snapshots_service.capture(db, hid)}


@router.get("/snapshots/net-worth", response_model=list[NetWorthPointOut])
def net_worth_history(
    days: int = 90,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> list[NetWorthPointOut]:
    return [
        NetWorthPointOut(
            on=p.on.isoformat(), assets=float(p.assets), debts=float(p.debts), net=float(p.net)
        )
        for p in snapshots_service.net_worth_series(db, hid, days=days)
    ]
