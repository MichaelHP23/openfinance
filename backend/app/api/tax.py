import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.schemas.tax import IncomeSummaryOut, RealizedGainOut, RealizedGainsOut
from app.services import tax

router = APIRouter(prefix="/tax", tags=["tax"])


@router.get("/realized-gains", response_model=RealizedGainsOut)
def get_realized_gains(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> RealizedGainsOut:
    r = tax.realized_gains(db, hid, year)
    return RealizedGainsOut(
        year=r.year,
        gains=[
            RealizedGainOut(
                security_id=g.security_id, symbol=g.symbol, account_id=g.account_id,
                opened_on=g.opened_on, closed_on=g.closed_on, quantity=g.quantity,
                proceeds=g.proceeds, cost_basis=g.cost_basis, gain=g.gain, term=g.term,
            )
            for g in r.gains
        ],
        short_term_gain=r.short_term_gain, long_term_gain=r.long_term_gain, total_gain=r.total_gain,
    )


@router.get("/income-summary", response_model=IncomeSummaryOut)
def get_income_summary(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> IncomeSummaryOut:
    s = tax.income_summary(db, hid, year)
    return IncomeSummaryOut(year=s.year, dividends=s.dividends, interest=s.interest, total=s.total)


@router.get("/export")
def get_tax_export(
    year: int, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> Response:
    csv_text = tax.export_csv(db, hid, year)
    return Response(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="realized-gains-{year}.csv"'},
    )
