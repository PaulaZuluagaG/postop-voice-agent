"""Entrada de texto por consola para pruebas sin micrófono."""

from __future__ import annotations

import asyncio

from loguru import logger
from pipecat.frames.frames import EndFrame, Frame, StartFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice.frames import PostOpUserTurnFrame


class ConsoleTextInputProcessor(FrameProcessor):
    """Lee líneas desde stdin tras el saludo inicial del agente."""

    def __init__(
        self,
        *,
        opening_ready: asyncio.Event | None = None,
        opening_failed: asyncio.Event | None = None,
        call_ended: asyncio.Event | None = None,
        prompt: str = "Paciente> ",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._opening_ready = opening_ready
        self._opening_failed = opening_failed
        self._call_ended = call_ended
        self._prompt = prompt
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._running = True
            self._task = asyncio.create_task(self._wait_for_opening_then_read())
        elif isinstance(frame, EndFrame):
            self._running = False
            if self._task:
                self._task.cancel()

        await self.push_frame(frame, direction)

    async def _wait_for_opening_then_read(self) -> None:
        if self._opening_ready is not None:
            ready = asyncio.create_task(self._opening_ready.wait())
            tasks: list[asyncio.Task[None]] = [ready]
            if self._opening_failed is not None:
                tasks.append(asyncio.create_task(self._opening_failed.wait()))
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            if self._opening_failed is not None and self._opening_failed.is_set():
                logger.error("Conversación abortada: falló el saludo inicial del agente.")
                self._running = False
                await self.push_frame(EndFrame())
                return
            if not self._opening_ready.is_set():
                return
        await self._read_loop()

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        logger.info("Modo texto activo. Escriba su mensaje y presione Enter ('salir' para cerrar).")

        while self._running:
            if self._call_ended is not None and self._call_ended.is_set():
                break
            try:
                line = await loop.run_in_executor(None, lambda: input(self._prompt))
            except (EOFError, KeyboardInterrupt):
                print()
                break

            text = line.strip()
            if not text:
                continue
            if text.lower() in {"salir", "exit", "quit"}:
                break

            await self.push_frame(PostOpUserTurnFrame(text=text))

        await self.push_frame(EndFrame())
