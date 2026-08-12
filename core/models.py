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
    CERVICAL_CANCER = "cervical_cancer"
    TOTAL_JOINT_REPLACEMENT = "total_joint_replacement"
    OTHER = "otro"


class ResponseCategory(StrEnum):
    RESPUESTA_VALIDA = "RESPUESTA_VALIDA"
    NO_LO_SE = "NO_LO_SE"
    ALERTA_IMPLICITA = "ALERTA_IMPLICITA"
    FUERA_DE_TONO = "FUERA_DE_TONO"
    NO_ENTIENDE = "NO_ENTIENDE"


class YesNo(StrEnum):
    SI = "si"
    NO = "no"


def coerce_yes_no(value: object) -> YesNo | None:
    """Normalize LLM or patient yes/no values into the YesNo enum."""
    if value is None:
        return None
    if isinstance(value, YesNo):
        return value
    if isinstance(value, bool):
        return YesNo.SI if value else YesNo.NO
    if isinstance(value, int) and value in (0, 1):
        return YesNo.SI if value else YesNo.NO
    if isinstance(value, str):
        normalized = value.strip().lower().replace("í", "i")
        if normalized in {"si", "yes", "true", "1"}:
            return YesNo.SI
        if normalized in {"no", "false", "0"}:
            return YesNo.NO
    return None


def coerce_optional_float(value: object) -> float | None:
    """Normalize numeric LLM facts that may arrive as strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", ".")
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def coerce_episode_count(value: object) -> int | None:
    """Normalize episode counts from numeric LLM output."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


class ParsedPage(BaseModel):
    page_number: int
    text: str


class ParsedDocument(BaseModel):
    source_id: str
    file_path: str
    file_name: str
    procedure_id: str
    procedure_scenario: ProcedureScenario
    document_type: DocumentType
    language: str
    content_hash: str
    page_count: int
    char_count: int
    pages: list[ParsedPage]


class TextChunk(BaseModel):
    chunk_id: str
    source_id: str
    text: str
    token_count: int
    chunk_index: int
    page_start: int
    page_end: int
    procedure_id: str
    procedure_scenario: ProcedureScenario
    document_type: DocumentType
    language: str
    file_name: str


class RetrievedChunk(TextChunk):
    score: float


class LLMTurnOutput(BaseModel):
    categoria: ResponseCategory
    foco_sintoma: str | None = None
    evidencia_suficiente: bool = False
    sintomas: dict[str, float | str | None] = Field(default_factory=dict)
    texto_paciente: str
    pregunta: str | None = None
    fuentes: list[str] = Field(default_factory=list)

    @property
    def implicit_alert(self) -> bool:
        return self.categoria == ResponseCategory.ALERTA_IMPLICITA


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
    llm_output: LLMTurnOutput | None = None
    symptoms: dict[str, object] = Field(default_factory=dict)
    protocol_procedure: str = "general"
    symptom_id: str | None = None
    base_score: int = 0
    day_factor: float = 1.0
    turn_score: int = 0
    weighted_score: int = 0
    cumulative_score: int = 0
    rules_applied: list[str] = Field(default_factory=list)
    alert_triggered: bool = False
    severity: SeverityLevel = SeverityLevel.GREEN
    timings: TurnTimings = Field(default_factory=TurnTimings)


class CallSessionState(BaseModel):
    call_id: UUID
    procedure_id: str
    procedure_scenario: ProcedureScenario
    postop_day: int
    patient_name: str = "Paciente"
    patient_id: str | None = None
    opening_message: str | None = None
    surgery_date: str | None = None
    custom_procedure: str | None = None
    uses_general_protocol: bool = False
    protocol_key: str = "general"
    protocol_symptoms: list[dict[str, object]] = Field(default_factory=list)
    protocol_thresholds: dict[str, int] = Field(default_factory=dict)
    protocol_alert_signs: list[str] = Field(default_factory=list)
    protocol_risk_factors: list[dict[str, object]] = Field(default_factory=list)
    patient_comorbidities: list[str] = Field(default_factory=list)
    risk_factor_bonus_applied: bool = False
    covered_symptoms: set[str] = Field(default_factory=list)
    current_focal_symptom: str | None = None
    cumulative_score: int = 0
    current_severity: SeverityLevel = SeverityLevel.GREEN
    alert_triggered: bool = False
    call_closed: bool = False
    last_closed_reason: str | None = None
    turn_count: int = 0
    turns: list[TurnRecord] = Field(default_factory=list)
    sources_used: set[str] = Field(default_factory=set)


class CallSummary(BaseModel):
    call_id: UUID
    procedure_id: str
    procedure_scenario: ProcedureScenario
    custom_procedure: str | None = None
    protocol_used: str = "general"
    postop_day: int
    patient_name: str = "Paciente"
    patient_id: str | None = None
    final_score: int
    severity: SeverityLevel
    decision_label: str = "verde"
    symptoms_reported: dict[str, object] = Field(default_factory=dict)
    next_steps: str = ""
    clinical_summary: str = ""
    alert_triggered: bool
    physician_escalated: bool = False
    vigilancia_recomendada: bool = False
    follow_up_recommended: bool = False
    sources_used: list[str]
    turn_count: int
    closed_reason: str
    turn_history: list[TurnRecord]


class SourceAggregate(BaseModel):
    source_id: str
    file_name: str
    procedure_id: str = ""
    procedure_scenario: ProcedureScenario
    document_type: DocumentType
    language: str
    chunk_count: int


class IngestReport(BaseModel):
    indexed_documents: int = 0
    total_chunks: int = 0
    skipped_no_text: list[str] = Field(default_factory=list)
    skipped_duplicates: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    protocol_generation: Any | None = None


class TraceEvent(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    call_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
