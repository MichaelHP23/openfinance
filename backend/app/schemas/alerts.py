from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.services.alerts import AlertKind


class AlertOut(BaseModel):
    key: str
    kind: AlertKind
    severity: Literal["info", "warn", "urgent"]
    title: str
    body: str
    href: str
    occurred_on: date
    model_config = {"from_attributes": True}


class DismissIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)
