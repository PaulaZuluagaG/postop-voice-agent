"""Local-only interactive chat demo to simulate a post-op patient conversation.

Usage:
    uv run python scripts/chat_demo.py
    uv run python scripts/chat_demo.py --name "María" --patient-id P001 \\
        --scenario appendicitis --surgery-date ayer
"""

from __future__ import annotations

import argparse
import sys

from agent.orchestrator import ConversationOrchestrator
from core.config import get_settings
from core.exceptions import ConfigurationError, PostOpError, SessionError
from core.models import CallSessionState, ProcedureScenario, TurnRecord
from core.registration import (
    PatientRegistration,
    prompt_patient_registration,
    registration_from_args,
)
from core.scenarios import SCENARIO_OPTIONS

SCENARIO_CHOICES = {scenario.value: scenario for _, _, scenario in SCENARIO_OPTIONS}
SCENARIO_CHOICES["otro"] = ProcedureScenario.OTHER


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local demo: simulate a patient conversation with the post-op agent.",
    )
    parser.add_argument("--name", default=None, help="Patient name.")
    parser.add_argument("--patient-id", default=None, help="Patient identifier.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_CHOICES),
        default=None,
        help="Surgery type (procedure scenario).",
    )
    parser.add_argument(
        "--surgery-date",
        default=None,
        help="Surgery date (YYYY-MM-DD, ayer, antier, hace N días).",
    )
    return parser


def _print_turn_metadata(session: CallSessionState, turn: TurnRecord) -> None:
    print(
        f"[turno {turn.turn_number} | "
        f"escenario: {session.procedure_scenario.value} | "
        f"día postop: {session.postop_day} | puntaje turno: {turn.turn_score} | "
        f"acumulado: {turn.cumulative_score} | severidad: {turn.severity.value} | "
        f"alerta: {turn.alert_triggered} | {turn.timings.total_ms:.0f}ms | "
        f"tokens: {turn.llm_usage.total_tokens if turn.llm_usage else 0}]\n"
    )


def _chat_loop(
    orchestrator: ConversationOrchestrator,
    session: CallSessionState,
    registration: PatientRegistration,
) -> int:
    while not session.call_closed:
        try:
            patient_message = input("Paciente> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not patient_message:
            continue
        if patient_message.lower() in {"salir", "exit", "quit"}:
            break

        try:
            turn = orchestrator.process_turn(session.call_id, patient_message)
        except SessionError as exc:
            print(f"Error de sesión: {exc}", file=sys.stderr)
            break
        except PostOpError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        session = orchestrator.get_session(session.call_id)
        print(f"\nAgente> {turn.agent_response}")
        _print_turn_metadata(session, turn)

    summary = orchestrator.close_call(session.call_id)
    print("\n--- Resumen de llamada ---")
    print(f"Puntaje final: {summary.final_score}")
    print(f"Severidad: {summary.severity.value}")
    print(f"Alerta: {summary.alert_triggered}")
    print(f"Turnos: {summary.turn_count}")
    if session.patient_id:
        print(f"Paciente: {session.patient_name} ({session.patient_id})")
    print(f"Tipo de cirugía: {registration.procedure_label}")
    print(f"Día postop: {session.postop_day}")
    print(f"Fuentes usadas: {len(summary.sources_used)}")
    print(f"Log: {get_settings().calls_log_dir / summary.call_id / 'summary' / 'events.json'}")
    return 0


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


def run_registered_chat(registration: PatientRegistration) -> int:
    orchestrator = ConversationOrchestrator()
    session = orchestrator.start_call(
        procedure_scenario=registration.procedure_scenario,
        patient_name=registration.patient_name,
        patient_id=registration.patient_id,
        postop_day=registration.postop_day,
        surgery_date=registration.surgery_date,
    )

    print(f"\nLlamada iniciada: {session.call_id}")
    print(
        f"Paciente: {registration.patient_name} ({registration.patient_id}) | "
        f"Tipo de cirugía: {registration.procedure_label} | "
        f"Día postop: {session.postop_day}"
    )
    print("Responda solo a las preguntas del agente. Comandos: 'salir' para cerrar.\n")
    opening = orchestrator.begin_triage(session.call_id)
    print(f"Agente> {opening}\n")

    return _chat_loop(orchestrator, session, registration)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        registration = _resolve_registration(args)
        return run_registered_chat(registration)
    except ConfigurationError as exc:
        print(f"Configuración incompleta: {exc}", file=sys.stderr)
        print(
            "Verifica GROQ_API_KEY y que Qdrant esté activo.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
