"""Punto de entrada del agente de voz Pipecat (consola)."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import sys

from core.ssl_certs import configure_ssl_certificates

configure_ssl_certificates()

from dotenv import load_dotenv  # noqa: E402
from loguru import logger  # noqa: E402
from pipecat.workers.runner import WorkerRunner  # noqa: E402

from core.config import get_settings
from core.exceptions import ConfigurationError, PostOpError
from core.models import ProcedureScenario
from core.scenarios import SCENARIO_OPTIONS
from scripts.patient_registration import (
    PatientRegistration,
    prompt_patient_registration,
    registration_from_args,
)
from voice.pipeline import (
    VoiceSession,
    build_text_pipeline,
    build_voice_pipeline,
    create_orchestrator_and_session,
)

SCENARIO_CHOICES = {scenario.value: scenario for _, _, scenario in SCENARIO_OPTIONS}
SCENARIO_CHOICES["otro"] = ProcedureScenario.OTHER


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agente médico de voz PostOp (Pipecat + Groq + Kokoro).",
    )
    parser.add_argument(
        "--mode",
        choices=("text", "voice"),
        default="text",
        help="text: escribe en consola; voice: micrófono local + Deepgram STT.",
    )
    parser.add_argument("--name", default=None, help="Nombre del paciente.")
    parser.add_argument("--patient-id", default=None, help="ID del paciente.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_CHOICES),
        default=None,
        help="Escenario clínico.",
    )
    parser.add_argument(
        "--surgery-date",
        default=None,
        help="Fecha de cirugía (YYYY-MM-DD, ayer, antier, hace N días).",
    )
    return parser


def _resolve_registration(args: argparse.Namespace) -> PatientRegistration:
    has_cli = any((args.name, args.patient_id, args.scenario, args.surgery_date))
    if has_cli:
        missing = [
            flag
            for flag, value in (
                ("--name", args.name),
                ("--patient-id", args.patient_id),
                ("--scenario", args.scenario),
                ("--surgery-date", args.surgery_date),
            )
            if not value
        ]
        if missing:
            print(
                f"Registro incompleto. Faltan: {', '.join(missing)}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return registration_from_args(
            patient_name=args.name,
            patient_id=args.patient_id,
            procedure_scenario=SCENARIO_CHOICES[args.scenario],
            surgery_date=args.surgery_date,
        )

    print("--- Registro del paciente (simula formulario UI) ---")
    return prompt_patient_registration()


def _print_call_banner(session: VoiceSession) -> None:
    """Réplica el preámbulo de ``scripts/chat_demo.py`` antes del saludo del agente."""
    registration = session.registration
    call_state = session.orchestrator.get_session(session.call_id)
    print(f"\nLlamada iniciada: {session.call_id}")
    print(
        f"Paciente: {registration.patient_name} ({registration.patient_id}) | "
        f"Tipo de cirugía: {registration.procedure_label} | "
        f"Cirugía: {registration.surgery_date} | Día postop: {call_state.postop_day} | "
        f"Modo: {session.mode}"
    )
    print("Responda solo a las preguntas del agente. Comandos: 'salir' para cerrar.\n")


async def _run_session(session: VoiceSession) -> int:
    runner = WorkerRunner(handle_sigint=True)
    await runner.add_workers(session.worker)
    await runner.run()

    call_state = session.orchestrator.get_session(session.call_id)
    if call_state.call_closed:
        summary = session.orchestrator.close_call(session.call_id, reason="pipeline_end")
    else:
        summary = session.orchestrator.close_call(session.call_id, reason="manual_close")
    print("\n--- Resumen de llamada ---")
    print(f"Puntaje final: {summary.final_score}")
    print(f"Severidad: {summary.severity.value}")
    print(f"Alerta: {summary.alert_triggered}")
    print(f"Turnos: {summary.turn_count}")
    print(f"Log: logs/calls/{summary.call_id}.jsonl")
    return 0


async def run_agent(args: argparse.Namespace) -> int:
    load_dotenv(override=True)
    settings = get_settings()

    if not settings.groq_api_key:
        raise ConfigurationError("GROQ_API_KEY es obligatorio")

    registration = _resolve_registration(args)
    orchestrator, call_id = create_orchestrator_and_session(registration, settings=settings)

    if args.mode == "voice":
        voice_session = build_voice_pipeline(orchestrator, call_id, settings=settings)
    else:
        voice_session = build_text_pipeline(orchestrator, call_id, settings=settings)

    _print_call_banner(voice_session)

    try:
        return await _run_session(voice_session)
    except PostOpError as exc:
        logger.error("Error clínico: {}", exc)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run_agent(args))
    except ConfigurationError as exc:
        print(f"Configuración incompleta: {exc}", file=sys.stderr)
        print("Verifica GROQ_API_KEY, DEEPGRAM_API_KEY (modo voz) y Qdrant.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
