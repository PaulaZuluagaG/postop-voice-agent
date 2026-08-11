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
    temp_id: str


class DocumentConfirmRequest(BaseModel):
    temp_id: str
    procedure_id: str
    file_name: str


class ErrorDetail(BaseModel):
    detail: str
