"""Pydantic domain models without business logic."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ResponseCategory(StrEnum):
    RESPUESTA_VALIDA = "RESPUESTA_VALIDA"
    NO_LO_SE = "NO_LO_SE"
    ALERTA_IMPLICITA = "ALERTA_IMPLICITA"
    FUERA_DE_TONO = "FUERA_DE_TONO"
    NO_ENTIENDE = "NO_ENTIENDE"


class ClinicalAxis(StrEnum):
    DOLOR = "dolor"
    HERIDA = "herida"
    DIGESTIVO = "digestivo"
    RESPIRACION = "respiracion"
    MOVILIDAD = "movilidad"
    NINGUNO = "ninguno"


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


class ClinicalFacts(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dolor_0_10: float | None = Field(default=None, alias="DOLOR_0_10", ge=0, le=10)
    fiebre_c: float | None = Field(default=None, alias="FIEBRE_C")
    disnea: YesNo | None = Field(default=None, alias="DISNEA")
    sangreado: YesNo | None = Field(default=None, alias="SANGREADO")
    vomitos: int | None = Field(default=None, alias="VOMITOS", ge=0)
    confusion: YesNo | None = Field(default=None, alias="CONFUSION")
    procedimiento: str | None = Field(default=None, alias="PROCEDIMIENTO")
    fecha_cirugia: str | None = Field(default=None, alias="FECHA_CIRUGIA")

    @field_validator("disnea", "sangreado", "confusion", mode="before")
    @classmethod
    def _coerce_yes_no_fields(cls, value: object) -> object:
        coerced = coerce_yes_no(value)
        return coerced if coerced is not None else value

    def to_patient_facts(self) -> PatientFacts:
        return PatientFacts(
            pain=self.dolor_0_10,
            fever_celsius=self.fiebre_c,
            dyspnea=_yes_no_to_bool(self.disnea),
            bleeding=_yes_no_to_bool(self.sangreado),
            vomiting_count=self.vomitos,
            confusion=_yes_no_to_bool(self.confusion),
        )


def _yes_no_to_bool(value: YesNo | None) -> bool | None:
    if value is None:
        return None
    return value == YesNo.SI


class LLMTurnOutput(BaseModel):
    categoria: ResponseCategory
    foco: ClinicalAxis = ClinicalAxis.NINGUNO
    evidencia_suficiente: bool = False
    hechos: ClinicalFacts = Field(default_factory=ClinicalFacts)
    texto_paciente: str
    pregunta: str | None = None
    fuentes: list[str] = Field(default_factory=list)

    @property
    def implicit_alert(self) -> bool:
        return self.categoria == ResponseCategory.ALERTA_IMPLICITA

    def to_patient_facts(self) -> PatientFacts:
        return self.hechos.to_patient_facts()


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
    patient_name: str = "Paciente"
    patient_id: str | None = None
    opening_message: str | None = None
    procedure_name: str | None = None
    surgery_date: str | None = None
    covered_axes: set[ClinicalAxis] = Field(default_factory=set)
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
