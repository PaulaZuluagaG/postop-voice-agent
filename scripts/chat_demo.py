"""Local-only interactive chat demo to simulate a post-op patient conversation.

Usage:
    uv run python scripts/chat_demo.py
    uv run python scripts/chat_demo.py --name "María" --patient-id P001 \\
        --scenario appendicitis --surgery-date ayer
    uv run python scripts/chat_demo.py --dev-triage --scenario appendicitis --postop-day 1
"""

from __future__ import annotations

import argparse
import sys

from agent.orchestrator import ConversationOrchestrator
from core.exceptions import ConfigurationError, PostOpError, SessionError
from core.models import CallSessionState, ProcedureScenario, TurnRecord
from scripts.patient_registration import (
    SCENARIO_OPTIONS,
    PatientRegistration,
    prompt_patient_registration,
    registration_from_args,
)

SCENARIO_CHOICES = {scenario.value: scenario for _, _, scenario in SCENARIO_OPTIONS}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local demo: simulate a patient conversation with the post-op agent.",
    )
    parser.add_argument(
        "--dev-triage",
        action="store_true",
        help="Developer mode: pick scenario and postop day only (no registration form).",
    )
    parser.add_argument("--name", default=None, help="Patient name.")
    parser.add_argument("--patient-id", default=None, help="Patient identifier.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_CHOICES),
        default=None,
        help="Procedure scenario (registration form option).",
    )
    parser.add_argument(
        "--procedure-name",
        default=None,
        help="Free-text procedure when using 'otro'.",
    )
    parser.add_argument(
        "--surgery-date",
        default=None,
        help="Surgery date (YYYY-MM-DD, ayer, antier, hace N días).",
    )
    parser.add_argument(
        "--postop-day",
        type=int,
        default=None,
        help="Post-operative day (dev-triage mode only).",
    )
    return parser


def _prompt_scenario() -> ProcedureScenario:
    print("Escenarios disponibles:")
    options = list(SCENARIO_CHOICES.items())
    for index, (name, _) in enumerate(options, start=1):
        print(f"  {index}. {name}")

    raw = input("Escenario [1]: ").strip() or "1"
    if raw.isdigit():
        choice = int(raw)
        if 1 <= choice <= len(options):
            return options[choice - 1][1]
    if raw in SCENARIO_CHOICES:
        return SCENARIO_CHOICES[raw]
    print(f"Opción inválida: {raw}", file=sys.stderr)
    raise SystemExit(1)


def _prompt_postop_day() -> int:
    raw = input("Día postoperatorio [1]: ").strip() or "1"
    try:
        day = int(raw)
    except ValueError:
        print(f"Día inválido: {raw}", file=sys.stderr)
        raise SystemExit(1) from None
    if day < 1:
        print("El día postoperatorio debe ser >= 1.", file=sys.stderr)
        raise SystemExit(1)
    return day


def _print_turn_metadata(session: CallSessionState, turn: TurnRecord) -> None:
    print(
        f"[turno {turn.turn_number} | "
        f"escenario: {session.procedure_scenario.value} | "
        f"día postop: {session.postop_day} | puntaje turno: {turn.turn_score} | "
        f"acumulado: {turn.cumulative_score} | severidad: {turn.severity.value} | "
        f"alerta: {turn.alert_triggered} | {turn.timings.total_ms:.0f}ms]\n"
    )


def _chat_loop(orchestrator: ConversationOrchestrator, session: CallSessionState) -> int:
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
    if summary.procedure_scenario.value != "general" or session.procedure_name:
        print(f"Procedimiento: {session.procedure_name or summary.procedure_scenario.value}")
    if session.surgery_date:
        print(f"Fecha cirugía: {session.surgery_date} | Día postop: {session.postop_day}")
    print(f"Fuentes usadas: {len(summary.sources_used)}")
    print(f"Log: logs/calls/{summary.call_id}.jsonl")
    return 0


def _resolve_registration(args: argparse.Namespace) -> PatientRegistration:
    has_cli = any(
        (
            args.name,
            args.patient_id,
            args.scenario,
            args.procedure_name,
            args.surgery_date,
        )
    )
    if has_cli:
        missing = [
            flag
            for flag, value in (
                ("--name", args.name),
                ("--patient-id", args.patient_id),
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
        scenario = SCENARIO_CHOICES[args.scenario] if args.scenario else ProcedureScenario.GENERAL
        if not args.scenario and not args.procedure_name:
            print("Indique --scenario o --procedure-name para 'otro'.", file=sys.stderr)
            raise SystemExit(1)
        return registration_from_args(
            patient_name=args.name,
            patient_id=args.patient_id,
            procedure_scenario=scenario,
            procedure_name=args.procedure_name,
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
        procedure_name=registration.procedure_name,
        surgery_date=registration.surgery_date,
    )

    print(f"\nLlamada iniciada: {session.call_id}")
    print(
        f"Paciente: {registration.patient_name} ({registration.patient_id}) | "
        f"Procedimiento: {registration.procedure_name} | "
        f"Cirugía: {registration.surgery_date} | Día postop: {session.postop_day}"
    )
    print("Responda solo a las preguntas del agente. Comandos: 'salir' para cerrar.\n")
    opening = orchestrator.begin_triage(session.call_id)
    print(f"Agente> {opening}\n")

    return _chat_loop(orchestrator, session)


def run_dev_triage_chat(scenario: ProcedureScenario, postop_day: int) -> int:
    orchestrator = ConversationOrchestrator()
    session = orchestrator.start_call(
        procedure_scenario=scenario,
        postop_day=postop_day,
    )

    print(f"\nLlamada iniciada: {session.call_id}")
    print(f"Modo: dev-triage | Escenario: {scenario.value} | Día postop: {postop_day}")
    print("Escribe como paciente. Comandos: 'salir' para cerrar.\n")
    opening = orchestrator.begin_triage(session.call_id)
    print(f"Agente> {opening}\n")

    return _chat_loop(orchestrator, session)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.dev_triage:
            scenario = SCENARIO_CHOICES[args.scenario] if args.scenario else _prompt_scenario()
            postop_day = args.postop_day if args.postop_day is not None else _prompt_postop_day()
            return run_dev_triage_chat(scenario, postop_day)

        registration = _resolve_registration(args)
        return run_registered_chat(registration)
    except ConfigurationError as exc:
        print(f"Configuración incompleta: {exc}", file=sys.stderr)
        print(
            "Verifica que Ollama esté corriendo (ollama serve) y que Qdrant esté activo.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
