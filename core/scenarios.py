"""Procedure scenario options shared by registration, ingest, and hot reload."""

from __future__ import annotations

from core.models import ProcedureScenario

SCENARIO_OPTIONS: tuple[tuple[str, str, ProcedureScenario], ...] = (
    ("1", "Apendicitis", ProcedureScenario.APPENDICITIS),
    ("2", "Colecistitis", ProcedureScenario.CHOLECYSTITIS),
    ("3", "Cáncer de cuello uterino", ProcedureScenario.CERVICAL_CANCER),
    ("4", "Cáncer colorrectal", ProcedureScenario.COLORECTAL_CANCER),
    ("5", "Reemplazo articular", ProcedureScenario.TOTAL_JOINT_REPLACEMENT),
)

SCENARIO_FOLDER_NAMES: dict[ProcedureScenario, str] = {
    ProcedureScenario.APPENDICITIS: "Appendicitis",
    ProcedureScenario.CHOLECYSTITIS: "cholecystitis",
    ProcedureScenario.CERVICAL_CANCER: "cuello uterino",
    ProcedureScenario.COLORECTAL_CANCER: "colorectal cancer",
    ProcedureScenario.TOTAL_JOINT_REPLACEMENT: "total joint replacement",
    ProcedureScenario.OTHER: "Otro",
}

FOLDER_TO_SCENARIO: dict[str, ProcedureScenario] = {
    folder.lower(): scenario for scenario, folder in SCENARIO_FOLDER_NAMES.items()
}
# Legacy folder name kept for backwards compatibility after EDA remediation.
FOLDER_TO_SCENARIO["breast_cancer"] = ProcedureScenario.CERVICAL_CANCER


def map_folder_to_scenario(folder_name: str) -> ProcedureScenario:
    scenario = FOLDER_TO_SCENARIO.get(folder_name.lower())
    if scenario is None:
        raise ValueError(f"Unknown procedure folder: {folder_name}")
    return scenario


def scenario_label(scenario: ProcedureScenario) -> str:
    for _key, label, option in SCENARIO_OPTIONS:
        if option == scenario:
            return label
    if scenario == ProcedureScenario.OTHER:
        return "Otro"
    return scenario.value.replace("_", " ")


def scenario_from_choice(raw: str) -> ProcedureScenario | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned == "6" or cleaned.lower() == "otro":
        return ProcedureScenario.OTHER
    for key, label, scenario in SCENARIO_OPTIONS:
        if cleaned == key or cleaned.lower() == label.lower():
            return scenario
    if cleaned in {scenario.value for _, _, scenario in SCENARIO_OPTIONS}:
        return ProcedureScenario(cleaned)
    return None
