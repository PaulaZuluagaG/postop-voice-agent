"""Pydantic models for structured post-operative protocols."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class SymptomLevel(BaseModel):
    min: float
    max: float
    points: int
    label: Literal["verde", "amarillo", "rojo"]


class SymptomDefinition(BaseModel):
    id: str
    question: str
    type: Literal["numeric", "binary", "qualitative"]
    levels: list[SymptomLevel]
    fuentes: list[str] = Field(default_factory=list)


class ProtocolThresholds(BaseModel):
    verde: int
    amarillo: int
    rojo: int


class PostOpProtocol(BaseModel):
    procedure: str
    version: str = "1.0"
    generated_at: datetime
    source_ids: list[str] = Field(default_factory=list)
    symptoms: list[SymptomDefinition]
    thresholds: ProtocolThresholds
    alert_signs: list[str] = Field(default_factory=list)

    @classmethod
    def from_llm_output(
        cls,
        data: dict,
        *,
        source_ids: list[str],
    ) -> PostOpProtocol:
        """Build a validated protocol from LLM JSON output."""
        payload = dict(data)
        payload["version"] = "1.0"
        payload["generated_at"] = datetime.now(tz=UTC)
        payload["source_ids"] = sorted(set(source_ids))
        return cls.model_validate(payload)


class ProcedureProtocolResult(BaseModel):
    procedure_scenario: str
    protocol_path: str
    chunks_retrieved: int
    qdrant_points_updated: int


class ProtocolGenerationReport(BaseModel):
    general_protocol_path: str
    procedures: list[ProcedureProtocolResult] = Field(default_factory=list)
    skipped_procedures: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
