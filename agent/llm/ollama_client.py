"""Local Ollama client with structured JSON parsing."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from ollama import Client

from agent.llm.payload_normalizer import normalize_llm_turn_payload
from agent.llm.prompts import SYSTEM_PROMPT, build_opening_user_prompt, build_user_prompt
from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.models import ClinicalAxis, LLMTurnOutput, RetrievedChunk
from core.retry import with_retry

logger = logging.getLogger(__name__)


class OllamaClient:
    """Thin wrapper around Ollama for structured turn outputs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = Client(host=self._settings.ollama_host)

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
            return with_retry(_call, operation_name="ollama_generate_turn")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama turn generation failed: {exc}") from exc

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
            return with_retry(_call, operation_name="ollama_generate_opening")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama opening generation failed: {exc}") from exc

    def _generate_structured(
        self,
        user_prompt: str,
        retrieved_chunks: list[RetrievedChunk],
    ) -> LLMTurnOutput:
        response = self._client.chat(
            model=self._settings.ollama_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            format=LLMTurnOutput.model_json_schema(),
            options={
                "temperature": self._settings.ollama_temperature,
                "num_predict": self._settings.ollama_max_output_tokens,
            },
        )
        raw_text = response.message.content or ""
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
