"""Patient registration form (CLI today, UI later)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from agent.decision.intake import resolve_surgery_date
from core.models import ProcedureScenario

SCENARIO_OPTIONS: tuple[tuple[str, str, ProcedureScenario], ...] = (
    ("1", "Apendicitis", ProcedureScenario.APPENDICITIS),
    ("2", "Colecistitis", ProcedureScenario.CHOLECYSTITIS),
    ("3", "Cáncer de mama", ProcedureScenario.BREAST_CANCER),
    ("4", "Cáncer colorrectal", ProcedureScenario.COLORECTAL_CANCER),
    ("5", "Reemplazo articular", ProcedureScenario.TOTAL_JOINT_REPLACEMENT),
)


@dataclass(frozen=True)
class PatientRegistration:
    patient_name: str
    patient_id: str
    procedure_scenario: ProcedureScenario
    procedure_name: str
    surgery_date: str


def _prompt_required(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if raw:
            return raw
        if default:
            return default
        print("Este campo es obligatorio.", file=sys.stderr)


def _prompt_surgery_date(reference_date: date | None = None) -> str:
    ref = reference_date or date.today()
    while True:
        raw = input("Fecha de cirugía (YYYY-MM-DD, ayer, antier, hace N días): ").strip()
        if not raw:
            print("La fecha es obligatoria.", file=sys.stderr)
            continue
        try:
            return resolve_surgery_date(raw, reference_date=ref).isoformat()
        except ValueError:
            print("Fecha no válida. Use YYYY-MM-DD o una expresión como 'ayer'.", file=sys.stderr)


def _prompt_procedure() -> tuple[ProcedureScenario, str]:
    print("Tipo de cirugía:")
    for key, label, _scenario in SCENARIO_OPTIONS:
        print(f"  {key}. {label}")
    print("  6. Otro")

    raw = input("Opción [1]: ").strip() or "1"
    if raw == "6" or raw.lower() == "otro":
        other = _prompt_required("Describa la cirugía")
        return ProcedureScenario.GENERAL, other

    for key, label, scenario in SCENARIO_OPTIONS:
        if raw == key or raw.lower() == label.lower():
            return scenario, label

    if raw in {scenario.value for _, _, scenario in SCENARIO_OPTIONS}:
        scenario = ProcedureScenario(raw)
        label = next(label for key, label, sc in SCENARIO_OPTIONS if sc == scenario)
        return scenario, label

    print(f"Opción inválida: {raw}", file=sys.stderr)
    raise SystemExit(1)


def prompt_patient_registration(reference_date: date | None = None) -> PatientRegistration:
    """Collect registration fields as the future UI form would."""
    patient_name = _prompt_required("Nombre del paciente")
    patient_id = _prompt_required("ID del paciente")
    procedure_scenario, procedure_name = _prompt_procedure()
    surgery_date = _prompt_surgery_date(reference_date=reference_date)
    return PatientRegistration(
        patient_name=patient_name,
        patient_id=patient_id,
        procedure_scenario=procedure_scenario,
        procedure_name=procedure_name,
        surgery_date=surgery_date,
    )


def registration_from_args(
    *,
    patient_name: str,
    patient_id: str,
    procedure_scenario: ProcedureScenario,
    procedure_name: str | None,
    surgery_date: str,
    reference_date: date | None = None,
) -> PatientRegistration:
    ref = reference_date or date.today()
    resolved = resolve_surgery_date(surgery_date, reference_date=ref).isoformat()
    label = procedure_name or next(
        (label for _, label, scenario in SCENARIO_OPTIONS if scenario == procedure_scenario),
        procedure_scenario.value.replace("_", " "),
    )
    return PatientRegistration(
        patient_name=patient_name,
        patient_id=patient_id,
        procedure_scenario=procedure_scenario,
        procedure_name=label,
        surgery_date=resolved,
    )
