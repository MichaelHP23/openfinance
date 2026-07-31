import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryOut, CategoryUpdate
from app.services import categories

router = APIRouter(prefix="/categories", tags=["categories"])


def _out(row: Category) -> CategoryOut:
    return CategoryOut(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        is_system=row.household_id is None,
    )


@router.get("", response_model=list[CategoryOut])
def list_categories(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[CategoryOut]:
    return [_out(c) for c in categories.list_for(db, hid)]


@router.post("", response_model=CategoryOut)
def create_category(
    body: CategoryCreate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryOut:
    try:
        return _out(categories.create(db, hid, body))
    except categories.UnknownParent as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID,
    body: CategoryUpdate,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> CategoryOut:
    try:
        row = categories.update(db, hid, category_id, body)
    except categories.SystemCategoryImmutable as exc:
        raise HTTPException(
            status_code=403, detail="System categories cannot be edited"
        ) from exc
    except categories.UnknownParent as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return _out(row)


@router.delete("/{category_id}")
def delete_category(
    category_id: uuid.UUID,
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        removed = categories.delete(db, hid, category_id)
    except categories.SystemCategoryImmutable as exc:
        raise HTTPException(
            status_code=403, detail="System categories cannot be deleted"
        ) from exc
    except categories.CategoryInUse as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"status": "ok"}
