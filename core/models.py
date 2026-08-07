"""Pydantic domain models without business logic."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SeverityLevel(StrEnum):
    GREEN = "verde"
    YELLOW = "amarillo"
    RED = "rojo"


class DocumentType(StrEnum):
    GUIDE = "guide"
    PROTOCOL = "protocol"
    PAPER = "paper"
    CARE_PLAN = "care_plan"
    PATIENT_INSTRUCTION = "patient_instruction"
    GENERAL = "general"
    OTHER = "other"


class ProcedureScenario(StrEnum):
    APPENDICITIS = "appendicitis"
    CHOLECYSTITIS = "cholecystitis"
    COLORECTAL_CANCER = "colorectal_cancer"
    BREAST_CANCER = "breast_cancer"
    TOTAL_JOINT_REPLACEMENT = "total_joint_replacement"
    GENERAL = "general"


class ParsedPage(BaseModel):
    page_number: int
    text: str


class ParsedDocument(BaseModel):
    source_id: str
    file_path: str
    file_name: str
    procedure_scenario: ProcedureScenario
    document_type: DocumentType
    language: str
    content_hash: str
    page_count: int
    char_count: int
    is_general: bool = False
    pages: list[ParsedPage]


class TextChunk(BaseModel):
    chunk_id: str
    source_id: str
    text: str
    token_count: int
    chunk_index: int
    page_start: int
    page_end: int
    procedure_scenario: ProcedureScenario
    document_type: DocumentType
    language: str
    file_name: str
    is_general: bool = False


class RetrievedChunk(TextChunk):
    score: float


class PatientFacts(BaseModel):
    pain: float | None = Field(default=None, ge=0, le=10)
    fever_celsius: float | None = None
    dyspnea: bool | None = None
    bleeding: bool | None = None
    vomiting_count: int | None = Field(default=None, ge=0)
    confusion: bool | None = None


class LLMTurnOutput(BaseModel):
    patient_message: str
    extracted_symptoms: PatientFacts = Field(default_factory=PatientFacts)
    implicit_alert: bool = False
    cited_source_ids: list[str] = Field(default_factory=list)
    no_evidence_topics: list[str] = Field(default_factory=list)


class TurnTimings(BaseModel):
    retrieval_ms: float = 0.0
    llm_ms: float = 0.0
    decision_ms: float = 0.0
    total_ms: float = 0.0


class TurnRecord(BaseModel):
    turn_number: int
    patient_input: str
    agent_response: str
    rag_query: str
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    symptoms: PatientFacts = Field(default_factory=PatientFacts)
    turn_score: int = 0
    cumulative_score: int = 0
    rules_applied: list[str] = Field(default_factory=list)
    alert_triggered: bool = False
    severity: SeverityLevel = SeverityLevel.GREEN
    timings: TurnTimings = Field(default_factory=TurnTimings)


class CallSessionState(BaseModel):
    call_id: UUID
    procedure_scenario: ProcedureScenario
    postop_day: int
    cumulative_score: int = 0
    current_severity: SeverityLevel = SeverityLevel.GREEN
    alert_triggered: bool = False
    call_closed: bool = False
    turn_count: int = 0
    turns: list[TurnRecord] = Field(default_factory=list)
    sources_used: set[str] = Field(default_factory=set)


class CallSummary(BaseModel):
    call_id: UUID
    procedure_scenario: ProcedureScenario
    postop_day: int
    final_score: int
    severity: SeverityLevel
    alert_triggered: bool
    sources_used: list[str]
    turn_count: int
    closed_reason: str
    turn_history: list[TurnRecord]


class SourceAggregate(BaseModel):
    source_id: str
    file_name: str
    procedure_scenario: ProcedureScenario
    document_type: DocumentType
    language: str
    chunk_count: int
    is_general: bool = False


class IngestReport(BaseModel):
    indexed_documents: int = 0
    total_chunks: int = 0
    skipped_no_text: list[str] = Field(default_factory=list)
    skipped_duplicates: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    call_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
