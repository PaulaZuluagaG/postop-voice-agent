"""Admin API request and response models."""

from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    source_id: str
    procedure_type: str
    file_name: str
    chunk_count: int = Field(ge=0)


class ProcedureTypeOption(BaseModel):
    value: str
    label: str


class ProcedureSuggestion(BaseModel):
    suggested_procedure: str
    suggested_procedure_label: str
    temp_id: str


class DocumentConfirmRequest(BaseModel):
    temp_id: str
    procedure_id: str
    file_name: str


class ErrorDetail(BaseModel):
    detail: str


class CallListItem(BaseModel):
    call_id: str
    patient_name: str
    patient_id: str | None = None
    procedure_id: str | None = None
    postop_day: int | None = None
    decision_label: str
    final_score: int = 0
    closed_reason: str | None = None
    closed_at: str | None = None
    turn_count: int = 0
