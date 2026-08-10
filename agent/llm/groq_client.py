"""Groq client for structured turn outputs and document validation."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from groq import Groq

from agent.llm.payload_normalizer import normalize_llm_turn_payload
from agent.llm.prompts import (
    DOCUMENT_VALIDATION_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_document_validation_prompt,
    build_opening_user_prompt,
    build_user_prompt,
)
from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.groq_limiter import groq_call_slot
from core.models import ClinicalAxis, LLMTurnOutput, ProcedureScenario, RetrievedChunk
from core.retry import with_groq_retry
from core.scenarios import scenario_label

logger = logging.getLogger(__name__)


class GroqClient:
    """Thin wrapper around Groq for structured turn outputs and ingest validation."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is required for LLM operations")
        self._client = Groq(api_key=self._settings.groq_api_key)

    def generate_turn(
        self,
        *,
        patient_message: str,
        patient_name: str,
        procedimiento: str,
        dia_postop: int,
        ejes_cubiertos: set[ClinicalAxis],
        ejes_pendientes: list[ClinicalAxis],
        puntaje_total: int,
        turno: int,
        max_turnos: int,
        conversation_history: str,
        retrieved_chunks: list[RetrievedChunk],
        reference_date: date | None = None,
    ) -> LLMTurnOutput:
        ref = reference_date or date.today()
        evidence_block = self._format_evidence(retrieved_chunks)
        user_prompt = build_user_prompt(
            patient_name=patient_name,
            procedimiento=procedimiento,
            dia_postop=dia_postop,
            ejes_cubiertos=ejes_cubiertos,
            ejes_pendientes=ejes_pendientes,
            puntaje_total=puntaje_total,
            turno=turno,
            max_turnos=max_turnos,
            historial=conversation_history,
            patient_text=patient_message,
            evidence_block=evidence_block,
            reference_date=ref.isoformat(),
        )

        def _call() -> LLMTurnOutput:
            return self._generate_structured(user_prompt, retrieved_chunks)

        try:
            return with_groq_retry(_call, operation_name="groq_generate_turn")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Groq turn generation failed: {exc}") from exc

    def generate_opening(
        self,
        *,
        patient_name: str,
        procedimiento: str,
        dia_postop: int,
        ejes_pendientes: list[ClinicalAxis],
        has_procedure_evidence: bool,
        retrieved_chunks: list[RetrievedChunk],
        reference_date: date | None = None,
    ) -> LLMTurnOutput:
        ref = reference_date or date.today()
        evidence_block = self._format_evidence(retrieved_chunks)
        user_prompt = build_opening_user_prompt(
            patient_name=patient_name,
            procedimiento=procedimiento,
            dia_postop=dia_postop,
            ejes_pendientes=ejes_pendientes,
            has_procedure_evidence=has_procedure_evidence,
            evidence_block=evidence_block,
            reference_date=ref.isoformat(),
        )

        def _call() -> LLMTurnOutput:
            return self._generate_structured(user_prompt, retrieved_chunks)

        try:
            return with_groq_retry(_call, operation_name="groq_generate_opening")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Groq opening generation failed: {exc}") from exc

    def validate_document_category(
        self,
        *,
        document_excerpt: str,
        procedure_scenario: ProcedureScenario,
    ) -> tuple[bool, str]:
        """Return whether the PDF topic matches the selected surgery category."""
        category_label = scenario_label(procedure_scenario)
        user_prompt = build_document_validation_prompt(
            document_excerpt=document_excerpt,
            category_label=category_label,
        )

        def _call() -> tuple[bool, str]:
            with groq_call_slot():
                response = self._client.chat.completions.create(
                    model=self._settings.groq_model,
                    messages=[
                        {"role": "system", "content": DOCUMENT_VALIDATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=256,
                    response_format={"type": "json_object"},
                )
            raw_text = response.choices[0].message.content or ""
            payload = self._parse_json(raw_text)
            coincide = bool(payload.get("coincide"))
            motivo = str(payload.get("motivo", "")).strip()
            if coincide:
                return True, motivo
            tema = str(payload.get("tema_detectado", "")).strip()
            detail = motivo or f"El documento parece tratar sobre {tema or 'otro tema'}."
            return False, (
                f"El documento no coincide con la categoría '{category_label}'. {detail}"
            )

        try:
            return with_groq_retry(_call, operation_name="groq_validate_document")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Groq document validation failed: {exc}") from exc

    def _generate_structured(
        self,
        user_prompt: str,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LLMTurnOutput:
        with groq_call_slot():
            response = self._client.chat.completions.create(
                model=self._settings.groq_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._settings.groq_temperature,
                max_tokens=self._settings.groq_max_output_tokens,
                response_format={"type": "json_object"},
            )
        raw_text = response.choices[0].message.content or ""
        payload = normalize_llm_turn_payload(self._parse_json(raw_text))
        output = LLMTurnOutput.model_validate(payload)
        return self._validate_sources(output, retrieved_chunks)

    @staticmethod
    def _format_evidence(chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return ""
        lines: list[str] = []
        for chunk in chunks:
            header = (
                f"[source_id={chunk.source_id} | {chunk.file_name} | "
                f"p.{chunk.page_start}-{chunk.page_end}]"
            )
            lines.append(f"{header}\n{chunk.text[:700]}")
        return "\n\n".join(lines)

    @staticmethod
    def _parse_json(raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    @staticmethod
    def _validate_sources(
        output: LLMTurnOutput,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LLMTurnOutput:
        valid_ids = {chunk.source_id for chunk in retrieved_chunks}
        filtered = [source_id for source_id in output.fuentes if source_id in valid_ids]
        return output.model_copy(update={"fuentes": filtered})
