"""Procedure scenario options shared by registration, ingest, and hot reload."""

from __future__ import annotations

from pathlib import Path

from core.models import ProcedureScenario

SCENARIO_OPTIONS: tuple[tuple[str, str, ProcedureScenario], ...] = (
    ("1", "Apendicitis", ProcedureScenario.APPENDICITIS),
    ("2", "Colecistitis", ProcedureScenario.CHOLECYSTITIS),
    ("3", "Cáncer de cuello uterino", ProcedureScenario.CERVICAL_CANCER),
    ("4", "Cáncer colorrectal", ProcedureScenario.COLORECTAL_CANCER),
    ("5", "Reemplazo articular", ProcedureScenario.TOTAL_JOINT_REPLACEMENT),
)

SCENARIO_FOLDER_NAMES: dict[ProcedureScenario, str] = {
    ProcedureScenario.APPENDICITIS: "appendicitis",
    ProcedureScenario.CHOLECYSTITIS: "cholecystitis",
    ProcedureScenario.CERVICAL_CANCER: "cervical-cancer",
    ProcedureScenario.COLORECTAL_CANCER: "colorectal-cancer",
    ProcedureScenario.TOTAL_JOINT_REPLACEMENT: "total-joint-replacement",
    ProcedureScenario.OTHER: "other",
}

FOLDER_TO_SCENARIO: dict[str, ProcedureScenario] = {
    folder.lower(): scenario for scenario, folder in SCENARIO_FOLDER_NAMES.items()
}
# Legacy folder names kept for backwards compatibility after dataset remediation.
_LEGACY_FOLDER_ALIASES: dict[str, ProcedureScenario] = {
    "breast_cancer": ProcedureScenario.CERVICAL_CANCER,
    "cuello uterino": ProcedureScenario.CERVICAL_CANCER,
    "colorectal cancer": ProcedureScenario.COLORECTAL_CANCER,
    "total joint replacement": ProcedureScenario.TOTAL_JOINT_REPLACEMENT,
    "otro": ProcedureScenario.OTHER,
}
FOLDER_TO_SCENARIO.update(_LEGACY_FOLDER_ALIASES)

OTHER_OPTION_VALUE = "other"
OTHER_OPTION_LABEL = "Otro"


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
        return OTHER_OPTION_LABEL
    return scenario.value.replace("_", " ")


def folder_display_label(folder_name: str) -> str:
    """Human-readable label for a `dataset/textos` folder."""
    scenario = FOLDER_TO_SCENARIO.get(folder_name.lower())
    if scenario is not None:
        return scenario_label(scenario)
    return folder_name


def list_procedure_options_from_disk(textos_dir: Path) -> list[tuple[str, str]]:
    """List dropdown options from folders in ``textos_dir``, always including other.

    Returns ``(value, label)`` pairs. ``value`` is the folder name on disk
    (or ``other``). New folders appear automatically the next time this is called.
    """
    options: list[tuple[str, str]] = []
    has_otro = False

    if textos_dir.is_dir():
        for path in sorted(textos_dir.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            if path.name.lower() == OTHER_OPTION_VALUE.lower():
                has_otro = True
                options.append((OTHER_OPTION_VALUE, OTHER_OPTION_LABEL))
                continue
            options.append((path.name, folder_display_label(path.name)))

    if not has_otro:
        options.append((OTHER_OPTION_VALUE, OTHER_OPTION_LABEL))
    return options


def scenario_from_choice(raw: str) -> ProcedureScenario | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned == "6" or cleaned.lower() == "otro":
        return ProcedureScenario.OTHER
    for key, label, scenario in SCENARIO_OPTIONS:
        if cleaned == key or cleaned.lower() == label.lower():
            return scenario
    folder_match = FOLDER_TO_SCENARIO.get(cleaned.lower())
    if folder_match is not None:
        return folder_match
    if cleaned in {scenario.value for _, _, scenario in SCENARIO_OPTIONS}:
        return ProcedureScenario(cleaned)
    if cleaned == ProcedureScenario.OTHER.value:
        return ProcedureScenario.OTHER
    return None


def resolve_procedure_selection(raw: str) -> ProcedureScenario:
    """Map a UI selection (folder name, label, or enum value) to a scenario.

    Unknown folder names fall back to ``OTHER`` so new ``dataset/textos``
    directories remain selectable without code changes.
    """
    scenario = scenario_from_choice(raw)
    if scenario is not None:
        return scenario
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Tipo de procedimiento vacío")
    return ProcedureScenario.OTHER
