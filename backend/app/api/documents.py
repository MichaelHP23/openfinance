import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_household
from app.core.db import get_db
from app.models.document import Document, DocumentKind
from app.schemas.document import DocumentOut
from app.services import documents

router = APIRouter(prefix="/documents", tags=["documents"])


def _out(doc: Document) -> DocumentOut:
    return DocumentOut.model_validate(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> list[DocumentOut]:
    return [_out(d) for d in documents.list_for(db, hid)]


@router.post("", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    kind: DocumentKind = Form(...),
    title: str = Form(...),
    notes: str | None = Form(None),
    hid: uuid.UUID = Depends(require_household),
    db: Session = Depends(get_db),
) -> DocumentOut:
    data = await file.read()
    doc = documents.save(
        db, hid, kind=kind, title=title, filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream", data=data, notes=notes,
    )
    return _out(doc)


@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> Response:
    doc = documents.get(db, hid, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = documents.read_plaintext(db, hid, document_id)
    except documents.DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(
        content=data, media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: uuid.UUID, hid: uuid.UUID = Depends(require_household), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not documents.delete(db, hid, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "ok"}
