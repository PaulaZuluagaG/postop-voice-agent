"""Streaming de respuestas estructuradas desde Groq."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date

from agent.llm.groq_client import GroqClient
from agent.llm.json_stream import JsonStringFieldExtractor
from agent.llm.payload_normalizer import normalize_llm_turn_payload
from agent.llm.prompts import SYSTEM_PROMPT, build_opening_user_prompt, build_user_prompt
from core.config import Settings, get_settings
from core.exceptions import LLMCancelledError, LLMError
from core.groq_limiter import agent_groq_call_slot
from core.llm_errors import groq_failure_to_llm_error
from core.models import LLMTurnOutput, RetrievedChunk
from core.retry import with_groq_retry
from knowledge.protocol.models import SymptomDefinition


@dataclass
class GroqStreamHandle:
    """Maneja tokens hablables y la salida estructurada final."""

    tokens: AsyncIterator[str]
    output_future: asyncio.Future[LLMTurnOutput]


async def drain_output_future(future: asyncio.Future[LLMTurnOutput]) -> None:
    """Await *future* and swallow errors to avoid unhandled future exceptions."""
    if future.cancelled():
        return
    try:
        await future
    except Exception:
        return


class GroqStreamingClient:
    """Cliente Groq con soporte de streaming para síntesis de voz."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        groq_client: GroqClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._groq = groq_client or GroqClient(self._settings)

    def stream_turn(
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
        cancel_event: asyncio.Event | None = None,
    ) -> GroqStreamHandle:
        ref = reference_date or date.today()
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
            evidence_block=GroqClient._format_evidence(retrieved_chunks),
            reference_date=ref.isoformat(),
            current_focal_symptom=current_focal_symptom,
        )
        return self._stream_structured(user_prompt, retrieved_chunks, cancel_event=cancel_event)

    def stream_opening(
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
        cancel_event: asyncio.Event | None = None,
    ) -> GroqStreamHandle:
        ref = reference_date or date.today()
        user_prompt = build_opening_user_prompt(
            patient_name=patient_name,
            procedimiento=procedimiento,
            dia_postop=dia_postop,
            pending_symptoms=pending_symptoms,
            alert_signs=alert_signs,
            has_procedure_evidence=has_procedure_evidence,
            uses_general_protocol=uses_general_protocol,
            evidence_block=GroqClient._format_evidence(retrieved_chunks),
            reference_date=ref.isoformat(),
        )
        return self._stream_structured(user_prompt, retrieved_chunks, cancel_event=cancel_event)

    def _stream_structured(
        self,
        user_prompt: str,
        retrieved_chunks: list[RetrievedChunk],
        *,
        cancel_event: asyncio.Event | None,
    ) -> GroqStreamHandle:
        loop = asyncio.get_running_loop()
        token_queue: asyncio.Queue[str | None] = asyncio.Queue()
        output_future: asyncio.Future[LLMTurnOutput] = loop.create_future()

        def worker() -> None:
            try:
                output = self._collect_stream_sync(
                    user_prompt,
                    retrieved_chunks,
                    lambda token: loop.call_soon_threadsafe(token_queue.put_nowait, token),
                    cancel_event,
                )
                loop.call_soon_threadsafe(output_future.set_result, output)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(output_future.set_exception, exc)
            finally:
                loop.call_soon_threadsafe(token_queue.put_nowait, None)

        loop.run_in_executor(None, worker)

        async def token_iterator() -> AsyncIterator[str]:
            while True:
                token = await token_queue.get()
                if token is None:
                    break
                yield token

        return GroqStreamHandle(tokens=token_iterator(), output_future=output_future)

    def _collect_stream_sync(
        self,
        user_prompt: str,
        retrieved_chunks: list[RetrievedChunk],
        on_token: Callable[[str], None],
        cancel_event: asyncio.Event | None,
    ) -> LLMTurnOutput:
        def _call() -> LLMTurnOutput:
            with agent_groq_call_slot():
                extractor = JsonStringFieldExtractor("texto_paciente")
                chunks: list[str] = []

                stream = self._groq._client.chat.completions.create(  # noqa: SLF001
                    model=self._settings.groq_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self._settings.groq_temperature,
                    max_tokens=self._settings.groq_max_output_tokens,
                    response_format={"type": "json_object"},
                    stream=True,
                )

                for chunk in stream:
                    if cancel_event and cancel_event.is_set():
                        break
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if not delta:
                        continue
                    chunks.append(delta)
                    spoken = extractor.feed(delta)
                    if spoken:
                        on_token(spoken)

            raw_text = "".join(chunks)
            if not raw_text.strip():
                if cancel_event and cancel_event.is_set():
                    raise LLMCancelledError("Groq streaming interrumpido")
                raise LLMError("Groq streaming devolvió una respuesta vacía")
            payload = normalize_llm_turn_payload(self._groq._parse_json(raw_text))  # noqa: SLF001
            output = LLMTurnOutput.model_validate(payload)
            return self._groq._validate_sources(output, retrieved_chunks)  # noqa: SLF001

        try:
            return with_groq_retry(_call, operation_name="groq_stream_structured")
        except LLMCancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise groq_failure_to_llm_error(exc, prefix="Groq streaming failed") from exc
