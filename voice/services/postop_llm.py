"""Servicio LLM de Pipecat conectado al orquestador clínico."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from uuid import UUID

from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

from agent.orchestrator import ConversationOrchestrator
from core.config import Settings, get_settings
from core.exceptions import LLMCancelledError, LLMError, SessionError
from voice.frames import PostOpUserTurnFrame


def _default_llm_settings() -> LLMSettings:
    """Settings Pipecat completos (store mode) para evitar campos NOT_GIVEN."""
    return LLMSettings(
        model=None,
        system_instruction=None,
        temperature=None,
        max_tokens=None,
        top_p=None,
        top_k=None,
        frequency_penalty=None,
        presence_penalty=None,
        seed=None,
        filter_incomplete_user_turns=False,
        user_turn_completion_config=None,
    )


class PostOpLLMService(LLMService):
    """Integra RAG + Groq streaming + lógica clínica del orquestador."""

    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        call_id: UUID,
        *,
        app_settings: Settings | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            settings=_default_llm_settings(),
            **kwargs,
        )
        self._app_settings = app_settings or get_settings()
        self._orchestrator = orchestrator
        self._call_id = call_id
        self._cancel_event = asyncio.Event()
        self._active_task: asyncio.Task[None] | None = None
        self._turn_lock = asyncio.Lock()
        self._last_processed_message: str | None = None
        self._opening_sent = False
        self._opening_ready = asyncio.Event()
        self._opening_failed = asyncio.Event()
        self._call_ended = asyncio.Event()

    @property
    def opening_ready(self) -> asyncio.Event:
        """Se activa cuando el saludo inicial (triage RAG) terminó con éxito."""
        return self._opening_ready

    @property
    def opening_failed(self) -> asyncio.Event:
        """Se activa si el triage inicial falló (p. ej. error de Groq)."""
        return self._opening_failed

    @property
    def call_ended(self) -> asyncio.Event:
        """Se activa cuando el orquestador cierra la llamada clínica."""
        return self._call_ended

    async def start(self, frame: StartFrame) -> None:
        """Inicia el servicio y emite el saludo clínico como en ``begin_triage``."""
        await super().start(frame)
        try:
            await self.speak_opening()
        except Exception as exc:  # noqa: BLE001
            logger.error("Fallo en triage inicial: {}", exc)
            print(
                f"\nError: no se pudo generar el saludo del agente ({exc}).\n",
                file=sys.stderr,
            )
            self._opening_failed.set()
            await self.push_frame(EndFrame())
            return
        self._opening_ready.set()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            self._cancel_event.set()
            if self._active_task and not self._active_task.done():
                self._active_task.cancel()
            return

        if isinstance(frame, LLMContextFrame | PostOpUserTurnFrame):
            await self._handle_turn(frame, direction)
            return

        await self.push_frame(frame, direction)

    async def speak_opening(self) -> None:
        """Ejecuta RAG bootstrap + mensaje de apertura (equivalente a ``begin_triage``)."""
        if self._opening_sent:
            return
        await self._stream_response(self._orchestrator.stream_opening_response(self._call_id))
        self._opening_sent = True
        session = self._orchestrator.get_session(self._call_id)
        if session.opening_message:
            print(f"Agente> {session.opening_message}\n")

    async def _handle_turn(
        self,
        frame: LLMContextFrame | PostOpUserTurnFrame,
        direction: FrameDirection,
    ) -> None:
        session = self._orchestrator.get_session(self._call_id)
        if session.call_closed:
            logger.info("Entrada ignorada: la llamada ya está cerrada.")
            await self._finalize_call()
            return

        if isinstance(frame, PostOpUserTurnFrame):
            patient_message = frame.text.strip()
        else:
            patient_message = self._extract_last_user_message(frame.context)

        if not patient_message:
            await self.push_frame(frame, direction)
            return

        if patient_message == self._last_processed_message:
            logger.debug("Turno ignorado: mensaje duplicado del paciente.")
            return

        if self._active_task and not self._active_task.done():
            logger.debug("Turno ignorado: generación LLM en curso.")
            return

        async with self._turn_lock:
            if patient_message == self._last_processed_message:
                logger.debug("Turno ignorado: mensaje duplicado del paciente.")
                return

            # InterruptionFrame may have set this while the agent was speaking; clear
            # before starting a fresh Groq stream for the patient's completed turn.
            self._cancel_event = asyncio.Event()

            stream = self._orchestrator.stream_turn_response(
                self._call_id,
                patient_message,
                cancel_event=self._cancel_event,
            )
            try:
                await self._stream_response(stream)
            except LLMCancelledError:
                logger.debug("Turno de voz cancelado por interrupción")
                return
            except LLMError as exc:
                if self._cancel_event.is_set():
                    logger.debug("Turno de voz abortado tras interrupción: {}", exc)
                    return
                logger.error("Error LLM en turno de voz: {}", exc)
                raise
            except SessionError as exc:
                logger.info("Turno ignorado: {}", exc)
                if self._orchestrator.get_session(self._call_id).call_closed:
                    await self._finalize_call()
                return

            self._last_processed_message = patient_message

        await self._after_turn()

    async def _after_turn(self) -> None:
        """Réplica el feedback de ``chat_demo`` tras cada turno."""
        session = self._orchestrator.get_session(self._call_id)
        if session.turns:
            last_turn = session.turns[-1]
            print(f"\nAgente> {last_turn.agent_response}")
            print(
                f"[turno {last_turn.turn_number} | puntaje: {last_turn.turn_score} | "
                f"acumulado: {last_turn.cumulative_score} | "
                f"severidad: {last_turn.severity.value} | "
                f"alerta: {last_turn.alert_triggered}]\n"
            )

        if session.call_closed:
            await self._finalize_call()

    async def _finalize_call(self) -> None:
        if self._call_ended.is_set():
            return
        self._call_ended.set()
        print("La llamada clínica ha finalizado. Gracias por su tiempo.\n")
        await self.push_frame(EndFrame())

    async def _stream_response(self, token_source: AsyncIterator[str]) -> None:
        self._cancel_event = asyncio.Event()

        async def run() -> None:
            await self.push_frame(LLMFullResponseStartFrame())
            await self.start_processing_metrics()
            try:
                async for token in token_source:
                    if self._cancel_event.is_set():
                        break
                    if token:
                        await self.push_frame(LLMTextFrame(token))
            finally:
                await self.stop_processing_metrics()
                await self.push_frame(LLMFullResponseEndFrame())

        self._active_task = asyncio.create_task(run())
        try:
            await self._active_task
        except SessionError:
            raise
        except asyncio.CancelledError:
            logger.debug("Generación LLM cancelada por interrupción")
        finally:
            self._active_task = None

    @staticmethod
    def _extract_last_user_message(context: LLMContext) -> str:
        for message in reversed(context.get_messages()):
            role = message.get("role")
            if role in {"user", "developer"} and message.get("content"):
                return str(message["content"]).strip()
        return ""
