"""Frames personalizados del agente de voz."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.frames.frames import DataFrame


@dataclass
class PostOpUserTurnFrame(DataFrame):
    """Turno de paciente simulado desde consola (sin STT)."""

    text: str
