"""Patient registration form (CLI today, UI later)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from agent.decision.intake import resolve_surgery_date
from core.models import ProcedureScenario
from core.scenarios import (
    SCENARIO_OPTIONS,
    procedure_display_label,
    resolve_procedure_selection,
)


@dataclass(frozen=True)
class PatientRegistration:
    patient_name: str
    patient_id: str
    surgery_date: str
    procedure_scenario: ProcedureScenario
    procedure_id: str
    custom_procedure: str | None = None
    uses_general_protocol: bool = False

    @property
    def procedure_label(self) -> str:
        if self.custom_procedure:
            return self.custom_procedure
        return procedure_display_label(self.procedure_id)


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


def _prompt_procedure() -> tuple[ProcedureScenario, str, str | None, bool]:
    print("Tipo de cirugía:")
    for key, label, _scenario in SCENARIO_OPTIONS:
        print(f"  {key}. {label}")
    print("  6. Otro")

    raw = input("Opción [1]: ").strip() or "1"
    selection = resolve_procedure_selection(raw)
    return (
        selection.procedure_scenario,
        selection.procedure_id,
        selection.custom_label,
        selection.uses_general_protocol,
    )


def prompt_patient_registration(reference_date: date | None = None) -> PatientRegistration:
    """Collect the four inputs the voice app receives."""
    patient_name = _prompt_required("Nombre del paciente")
    patient_id = _prompt_required("ID del paciente")
    procedure_scenario, procedure_id, custom_procedure, uses_general = _prompt_procedure()
    surgery_date = _prompt_surgery_date(reference_date=reference_date)
    return PatientRegistration(
        patient_name=patient_name,
        patient_id=patient_id,
        surgery_date=surgery_date,
        procedure_scenario=procedure_scenario,
        procedure_id=procedure_id,
        custom_procedure=custom_procedure,
        uses_general_protocol=uses_general,
    )


def registration_from_frontend(payload: dict[str, str]) -> PatientRegistration:
    """Build registration from the María intake form (browser JSON)."""
    name = payload.get("name", "").strip()
    patient_id = payload.get("patientId", "").strip()
    surgery_date = payload.get("surgeryDate", "").strip()
    procedure = payload.get("procedure", "").strip()
    custom_procedure = payload.get("customProcedure", "").strip() or None
    missing = [
        label
        for label, value in (
            ("name", name),
            ("patientId", patient_id),
            ("surgeryDate", surgery_date),
            ("procedure", procedure),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Datos de paciente incompletos: {', '.join(missing)}")

    selection = resolve_procedure_selection(procedure, custom_label=custom_procedure)
    return PatientRegistration(
        patient_name=name,
        patient_id=patient_id,
        surgery_date=resolve_surgery_date(surgery_date).isoformat(),
        procedure_scenario=selection.procedure_scenario,
        procedure_id=selection.procedure_id,
        custom_procedure=selection.custom_label,
        uses_general_protocol=selection.uses_general_protocol,
    )


def registration_from_args(
    *,
    patient_name: str,
    patient_id: str,
    surgery_date: str,
    procedure_scenario: ProcedureScenario,
    procedure_id: str | None = None,
    custom_procedure: str | None = None,
    uses_general_protocol: bool = False,
    reference_date: date | None = None,
) -> PatientRegistration:
    ref = reference_date or date.today()
    resolved = resolve_surgery_date(surgery_date, reference_date=ref).isoformat()
    from core.scenarios import scenario_to_procedure_id

    return PatientRegistration(
        patient_name=patient_name,
        patient_id=patient_id,
        surgery_date=resolved,
        procedure_scenario=procedure_scenario,
        procedure_id=procedure_id or scenario_to_procedure_id(procedure_scenario),
        custom_procedure=custom_procedure,
        uses_general_protocol=uses_general_protocol,
    )
