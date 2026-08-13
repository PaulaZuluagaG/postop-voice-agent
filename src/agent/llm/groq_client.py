"""Groq client for structured agent turn outputs."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from groq import Groq

from agent.llm.payload_normalizer import normalize_llm_turn_payload
from agent.llm.prompts import SYSTEM_PROMPT, build_opening_user_prompt, build_user_prompt
from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.groq_limiter import agent_groq_call_slot
from core.llm_errors import groq_failure_to_llm_error
from core.models import LLMTurnOutput, LLMUsage, RetrievedChunk
from core.retry import with_groq_retry
from knowledge.protocol.models import SymptomDefinition

logger = logging.getLogger(__name__)


class GroqClient:
    """Thin wrapper around Groq for structured agent turn outputs."""

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
        covered_symptom_ids: set[str],
        pending_symptoms: list[SymptomDefinition],
        alert_signs: list[str],
        puntaje_total: int,
        turno: int,
        max_turnos: int,
        conversation_history: str,
        accumulated_facts: str,
        retrieved_chunks: list[RetrievedChunk],
        reference_date: date | None = None,
        current_focal_symptom: str | None = None,
    ) -> LLMTurnOutput:
        ref = reference_date or date.today()
        evidence_block = self._format_evidence(retrieved_chunks)
        user_prompt = build_user_prompt(
            patient_name=patient_name,
            procedimiento=procedimiento,
            dia_postop=dia_postop,
            covered_symptom_ids=covered_symptom_ids,
            pending_symptoms=pending_symptoms,
            alert_signs=alert_signs,
            puntaje_total=puntaje_total,
            turno=turno,
            max_turnos=max_turnos,
            historial=conversation_history,
            sintomas_acumulados=accumulated_facts,
            patient_text=patient_message,
            evidence_block=evidence_block,
            reference_date=ref.isoformat(),
            current_focal_symptom=current_focal_symptom,
        )

        def _call() -> tuple[LLMTurnOutput, LLMUsage]:
            return self._generate_structured(user_prompt, retrieved_chunks)

        try:
            return with_groq_retry(_call, operation_name="groq_generate_turn")
        except Exception as exc:  # noqa: BLE001
            raise groq_failure_to_llm_error(exc, prefix="Groq turn generation failed") from exc

    def generate_opening(
        self,
        *,
        patient_name: str,
        procedimiento: str,
        dia_postop: int,
        pending_symptoms: list[SymptomDefinition],
        alert_signs: list[str],
        has_procedure_evidence: bool,
        uses_general_protocol: bool,
        retrieved_chunks: list[RetrievedChunk],
        reference_date: date | None = None,
    ) -> LLMTurnOutput:
        ref = reference_date or date.today()
        evidence_block = self._format_evidence(retrieved_chunks)
        user_prompt = build_opening_user_prompt(
            patient_name=patient_name,
            procedimiento=procedimiento,
            dia_postop=dia_postop,
            pending_symptoms=pending_symptoms,
            alert_signs=alert_signs,
            has_procedure_evidence=has_procedure_evidence,
            uses_general_protocol=uses_general_protocol,
            evidence_block=evidence_block,
            reference_date=ref.isoformat(),
        )

        def _call() -> tuple[LLMTurnOutput, LLMUsage]:
            return self._generate_structured(user_prompt, retrieved_chunks)

        try:
            return with_groq_retry(_call, operation_name="groq_generate_opening")
        except Exception as exc:  # noqa: BLE001
            raise groq_failure_to_llm_error(exc, prefix="Groq opening generation failed") from exc

    def _generate_structured(
        self,
        user_prompt: str,
        retrieved_chunks: list[RetrievedChunk],
    ) -> tuple[LLMTurnOutput, LLMUsage]:
        with agent_groq_call_slot():
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

        raw = response.choices[0].message.content or ""
        payload = self._parse_json(raw)
        payload = normalize_llm_turn_payload(payload)
        output = LLMTurnOutput.model_validate(payload)
        output = self._sanitize_sources(output, retrieved_chunks)
        usage = self._parse_usage(response.usage)
        return output, usage

    @staticmethod
    def _parse_usage(usage: object | None) -> LLMUsage:
        if usage is None:
            return LLMUsage()
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or 0)
        if total == 0:
            total = prompt + completion
        return LLMUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Invalid JSON from Groq: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMError("Groq response is not a JSON object")
        return parsed

    @staticmethod
    def _validate_sources(
        output: LLMTurnOutput,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LLMTurnOutput:
        return GroqClient._sanitize_sources(output, retrieved_chunks)

    @staticmethod
    def _sanitize_sources(
        output: LLMTurnOutput,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LLMTurnOutput:
        allowed = {chunk.source_id for chunk in retrieved_chunks}
        filtered = [source_id for source_id in output.fuentes if source_id in allowed]
        if filtered != output.fuentes:
            return output.model_copy(update={"fuentes": filtered})
        return output

    @staticmethod
    def _format_evidence(chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return ""
        lines: list[str] = []
        for chunk in chunks:
            excerpt = chunk.text[:500].replace("\n", " ")
            lines.append(f"[{chunk.source_id}] (score={chunk.score:.2f}) {excerpt}")
        return "\n".join(lines)
