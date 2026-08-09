from pydantic import BaseModel


class ChecklistItemOut(BaseModel):
    label: str
    satisfied: bool
    detail: str


class ChecklistOut(BaseModel):
    items: list[ChecklistItemOut]
    gaps: int
