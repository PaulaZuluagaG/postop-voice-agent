"""Local-only interactive chat demo to simulate a post-op patient conversation.

Usage:
    uv run python scripts/chat_demo.py
    uv run python scripts/chat_demo.py --scenario cholecystitis --postop-day 1
"""

from __future__ import annotations

import argparse
import sys

from agent.orchestrator import ConversationOrchestrator
from core.exceptions import ConfigurationError, PostOpError, SessionError
from core.models import ProcedureScenario

SCENARIO_CHOICES = {
    "appendicitis": ProcedureScenario.APPENDICITIS,
    "cholecystitis": ProcedureScenario.CHOLECYSTITIS,
    "breast_cancer": ProcedureScenario.BREAST_CANCER,
    "colorectal_cancer": ProcedureScenario.COLORECTAL_CANCER,
    "total_joint_replacement": ProcedureScenario.TOTAL_JOINT_REPLACEMENT,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local demo: simulate a patient conversation with the post-op agent.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_CHOICES),
        default=None,
        help="Procedure scenario (prompted if omitted).",
    )
    parser.add_argument(
        "--postop-day",
        type=int,
        default=None,
        help="Post-operative day (prompted if omitted).",
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


def run_chat(scenario: ProcedureScenario, postop_day: int) -> int:
    orchestrator = ConversationOrchestrator()
    session = orchestrator.start_call(
        procedure_scenario=scenario,
        postop_day=postop_day,
    )

    print(f"\nLlamada iniciada: {session.call_id}")
    print(f"Escenario: {scenario.value} | Día postop: {postop_day}")
    print("Escribe como paciente. Comandos: 'salir' para cerrar.\n")

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

        print(f"\nAgente> {turn.agent_response}")
        print(
            f"[turno {turn.turn_number} | puntaje turno: {turn.turn_score} | "
            f"acumulado: {turn.cumulative_score} | severidad: {turn.severity.value} | "
            f"alerta: {turn.alert_triggered} | {turn.timings.total_ms:.0f}ms]\n"
        )
        session = orchestrator.get_session(session.call_id)

    summary = orchestrator.close_call(session.call_id)
    print("\n--- Resumen de llamada ---")
    print(f"Puntaje final: {summary.final_score}")
    print(f"Severidad: {summary.severity.value}")
    print(f"Alerta: {summary.alert_triggered}")
    print(f"Turnos: {summary.turn_count}")
    print(f"Fuentes usadas: {len(summary.sources_used)}")
    print(f"Log: logs/calls/{summary.call_id}.jsonl")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scenario = SCENARIO_CHOICES[args.scenario] if args.scenario else _prompt_scenario()
    postop_day = args.postop_day if args.postop_day is not None else _prompt_postop_day()

    try:
        return run_chat(scenario, postop_day)
    except ConfigurationError as exc:
        print(f"Configuración incompleta: {exc}", file=sys.stderr)
        print("Verifica GOOGLE_API_KEY en .env y que Qdrant esté corriendo.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
