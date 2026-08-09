"""Admin document management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from api.auth import require_admin_token
from api.schemas import DocumentItem, ProcedureTypeOption
from api.services.documents import (
    DocumentNotFoundError,
    DocumentService,
    DocumentValidationError,
    get_document_service,
)
from core.exceptions import InsufficientTextError, LLMError, PostOpError
from core.models import ProcedureScenario

router = APIRouter(tags=["admin"])


@router.get("/procedure-types", response_model=list[ProcedureTypeOption])
def list_procedure_types(
    _: None = Depends(require_admin_token),
    service: DocumentService = Depends(get_document_service),
) -> list[ProcedureTypeOption]:
    return service.list_procedure_types()


@router.get("/documents", response_model=list[DocumentItem])
def list_documents(
    _: None = Depends(require_admin_token),
    service: DocumentService = Depends(get_document_service),
) -> list[DocumentItem]:
    return service.list_documents()


@router.post("/documents", response_model=DocumentItem, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    procedure_type: str = Form(...),
    _: None = Depends(require_admin_token),
    service: DocumentService = Depends(get_document_service),
) -> DocumentItem:
    if not procedure_type.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="procedure_type es obligatorio.",
        )

    try:
        scenario = ProcedureScenario(procedure_type.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"procedure_type inválido: {procedure_type}",
        ) from exc

    file_name = file.filename or ""
    if not file_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo se admiten archivos PDF.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El archivo PDF está vacío.",
        )

    try:
        return service.upload_document(
            file_name=file_name,
            file_bytes=file_bytes,
            procedure_scenario=scenario,
        )
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except InsufficientTextError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error de validación LLM: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except PostOpError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.delete("/documents/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    source_id: str,
    _: None = Depends(require_admin_token),
    service: DocumentService = Depends(get_document_service),
) -> None:
    try:
        service.delete_document(source_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PostOpError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
