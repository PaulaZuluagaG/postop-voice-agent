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
    CERVICAL_CANCER = "cervical_cancer"
    TOTAL_JOINT_REPLACEMENT = "total_joint_replacement"
    OTHER = "otro"


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


def resolve_vomiting_count(
    presence: YesNo | None,
    episodes: int | None,
) -> int | None:
    """Map LLM vomiting facts to a single count for scoring."""
    if episodes is not None:
        return episodes
    if presence == YesNo.SI:
        return 1
    if presence == YesNo.NO:
        return 0
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
    vomitos: YesNo | None = Field(default=None, alias="VOMITOS")
    vomitos_episodios: int | None = Field(default=None, alias="VOMITOS_EPISODIOS", ge=0)
    confusion: YesNo | None = Field(default=None, alias="CONFUSION")
    procedimiento: str | None = Field(default=None, alias="PROCEDIMIENTO")
    fecha_cirugia: str | None = Field(default=None, alias="FECHA_CIRUGIA")

    @field_validator("dolor_0_10", "fiebre_c", mode="before")
    @classmethod
    def _coerce_numeric_fields(cls, value: object) -> object:
        coerced = coerce_optional_float(value)
        return coerced if coerced is not None else value

    @field_validator("disnea", "sangreado", "confusion", "vomitos", mode="before")
    @classmethod
    def _coerce_yes_no_fields(cls, value: object) -> object:
        coerced = coerce_yes_no(value)
        return coerced if coerced is not None else value

    @field_validator("vomitos_episodios", mode="before")
    @classmethod
    def _coerce_episode_count_field(cls, value: object) -> object:
        coerced = coerce_episode_count(value)
        return coerced if coerced is not None else value

    def resolved_vomiting_count(self) -> int | None:
        return resolve_vomiting_count(self.vomitos, self.vomitos_episodios)

    def to_patient_facts(self) -> PatientFacts:
        return PatientFacts(
            pain=self.dolor_0_10,
            fever_celsius=self.fiebre_c,
            dyspnea=_yes_no_to_bool(self.disnea),
            bleeding=_yes_no_to_bool(self.sangreado),
            vomiting_count=self.resolved_vomiting_count(),
            confusion=_yes_no_to_bool(self.confusion),
        )


def _yes_no_to_bool(value: YesNo | None) -> bool | None:
    if value is None:
        return None
    return value == YesNo.SI


class LLMTurnOutput(BaseModel):
    categoria: ResponseCategory
    foco: ClinicalAxis = ClinicalAxis.NINGUNO
    foco_sintoma: str | None = None
    evidencia_suficiente: bool = False
    hechos: ClinicalFacts = Field(default_factory=ClinicalFacts)
    sintomas: dict[str, float | str | None] = Field(default_factory=dict)
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
    covered_axes: set[ClinicalAxis] = Field(default_factory=set)
    covered_symptoms: set[str] = Field(default_factory=set)
    current_focal_symptom: str | None = None
    cumulative_score: int = 0
    current_severity: SeverityLevel = SeverityLevel.GREEN
    alert_triggered: bool = False
    call_closed: bool = False
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
    final_score: int
    severity: SeverityLevel
    alert_triggered: bool
    physician_escalated: bool = False
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
