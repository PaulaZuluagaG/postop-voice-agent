"""Admin document management routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from google.api_core.exceptions import GoogleAPIError, ResourceExhausted

from api.auth import require_admin_token
from api.schemas import CallListItem, DocumentItem, ProcedureSuggestion, ProcedureTypeOption
from api.services.calls import CallLogService
from api.services.documents import (
    DocumentNotFoundError,
    DocumentService,
    DocumentValidationError,
    PendingUploadNotFoundError,
    get_document_service,
)
from core.exceptions import DuplicateDocumentError, InsufficientTextError, LLMError, PostOpError
from core.models import CallSummary
from core.retry import gemini_is_daily_quota_error

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


def get_call_log_service() -> CallLogService:
    return CallLogService()


def _gemini_error_detail(exc: Exception) -> str:
    if gemini_is_daily_quota_error(exc):
        return (
            "Cuota diaria de Gemini agotada. Espera al reset diario o cambia GEMINI_MODEL "
            "en .env antes de volver a clasificar documentos."
        )
    if isinstance(exc, ResourceExhausted):
        return "Gemini rechazó la solicitud por límite de tasa. Intenta de nuevo en un minuto."
    if isinstance(exc, LLMError):
        return str(exc)
    if isinstance(exc, PostOpError):
        return str(exc)
    if isinstance(exc, GoogleAPIError):
        return f"Error de Gemini: {exc}"
    return "No se pudo clasificar el documento. Revisa los logs del servidor."


def _raise_gemini_http_error(exc: Exception) -> None:
    logger.exception("Gemini operation failed during admin document flow")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=_gemini_error_detail(exc),
    ) from exc


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


@router.post("/documents/analyze", response_model=ProcedureSuggestion)
async def analyze_document(
    file: UploadFile = File(...),
    _: None = Depends(require_admin_token),
    service: DocumentService = Depends(get_document_service),
) -> ProcedureSuggestion:
    file_name, file_bytes = await _read_pdf_upload(file)
    try:
        return service.analyze_document(file_name=file_name, file_bytes=file_bytes)
    except DuplicateDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientTextError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LLMError as exc:
        _raise_gemini_http_error(exc)
    except (ResourceExhausted, GoogleAPIError) as exc:
        _raise_gemini_http_error(exc)
    except PostOpError as exc:
        _raise_gemini_http_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error analyzing document %s", file_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al analizar el documento.",
        ) from exc


@router.post("/documents/confirm", response_model=DocumentItem, status_code=status.HTTP_201_CREATED)
async def confirm_document(
    temp_id: str = Form(...),
    procedure_id: str = Form(...),
    file_name: str = Form(...),
    procedure_label: str = Form(""),
    _: None = Depends(require_admin_token),
    service: DocumentService = Depends(get_document_service),
) -> DocumentItem:
    try:
        return service.confirm_document(
            temp_id=temp_id.strip(),
            procedure_id=procedure_id.strip(),
            file_name=file_name.strip(),
            procedure_label=procedure_label.strip() or None,
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PendingUploadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMError as exc:
        _raise_gemini_http_error(exc)
    except (ResourceExhausted, GoogleAPIError) as exc:
        _raise_gemini_http_error(exc)
    except PostOpError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


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

    file_name, file_bytes = await _read_pdf_upload(file)

    try:
        return service.upload_document(
            file_name=file_name,
            file_bytes=file_bytes,
            procedure_id=procedure_type.strip(),
        )
    except DuplicateDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except InsufficientTextError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LLMError as exc:
        _raise_gemini_http_error(exc)
    except (ResourceExhausted, GoogleAPIError) as exc:
        _raise_gemini_http_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except PostOpError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


async def _read_pdf_upload(file: UploadFile) -> tuple[str, bytes]:
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
    return file_name, file_bytes


@router.get("/calls", response_model=list[CallListItem])
def list_recent_calls(
    limit: int = 50,
    _: None = Depends(require_admin_token),
    service: CallLogService = Depends(get_call_log_service),
) -> list[CallListItem]:
    return [CallListItem.model_validate(item) for item in service.list_recent_calls(limit=limit)]


@router.get("/calls/{call_id}", response_model=CallSummary)
def get_call_summary(
    call_id: str,
    _: None = Depends(require_admin_token),
    service: CallLogService = Depends(get_call_log_service),
) -> CallSummary:
    summary = service.get_call_summary(call_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Llamada no encontrada: {call_id}",
        )
    return summary
