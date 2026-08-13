"""Procedure scenario options shared by registration, ingest, and hot reload."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.models import ProcedureScenario
from core.procedure_labels import get_procedure_label

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

_SCENARIO_VALUE_TO_FOLDER: dict[str, str] = {
    scenario.value: folder for scenario, folder in SCENARIO_FOLDER_NAMES.items()
}

_PROCEDURE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


@dataclass(frozen=True)
class ProcedureSelection:
    """Resolved procedure identity for ingest, voice, and agent runtime."""

    procedure_id: str
    procedure_scenario: ProcedureScenario
    is_other: bool = False
    custom_label: str | None = None
    uses_general_protocol: bool = False


def normalize_procedure_id(raw: str) -> str:
    """Normalize a procedure folder slug."""
    cleaned = raw.strip().lower().replace(" ", "-")
    return cleaned


def canonical_procedure_id(raw: str) -> str:
    """Map enum values and aliases to the canonical folder slug under ``textos/``."""
    cleaned = raw.strip().lower()
    if not cleaned:
        return cleaned

    folder = _SCENARIO_VALUE_TO_FOLDER.get(cleaned)
    if folder is not None:
        return folder

    normalized = normalize_procedure_id(cleaned)
    scenario = FOLDER_TO_SCENARIO.get(normalized)
    if scenario is not None:
        return scenario_to_procedure_id(scenario)

    return normalized


def legacy_protocol_directory_names(procedure_id: str) -> list[str]:
    """Non-canonical protocol directory names that alias the same procedure."""
    canonical = canonical_procedure_id(procedure_id)
    aliases: set[str] = set()
    scenario = FOLDER_TO_SCENARIO.get(canonical)
    if scenario is not None:
        aliases.add(scenario.value)
    aliases.discard(canonical)
    return sorted(aliases)


def is_valid_procedure_id(procedure_id: str) -> bool:
    return bool(_PROCEDURE_ID_PATTERN.match(procedure_id))


def map_folder_to_scenario(folder_name: str) -> ProcedureScenario:
    scenario = FOLDER_TO_SCENARIO.get(folder_name.lower())
    if scenario is None:
        raise ValueError(f"Unknown procedure folder: {folder_name}")
    return scenario


def resolve_folder_scenario(folder_name: str) -> tuple[str, ProcedureScenario]:
    """Map a dataset folder to ``(procedure_id, scenario)``, allowing new folders."""
    procedure_id = normalize_procedure_id(folder_name)
    scenario = FOLDER_TO_SCENARIO.get(procedure_id)
    if scenario is None:
        return procedure_id, ProcedureScenario.OTHER
    return procedure_id, scenario


def scenario_to_procedure_id(scenario: ProcedureScenario) -> str:
    return SCENARIO_FOLDER_NAMES.get(scenario, scenario.value)


def qdrant_filter_values(procedure_id: str) -> list[str]:
    """Return payload values that may identify a procedure in Qdrant."""
    canonical = canonical_procedure_id(procedure_id)
    values = {canonical, procedure_id.strip().lower()}
    scenario = FOLDER_TO_SCENARIO.get(canonical)
    if scenario is not None:
        values.add(scenario.value)
    return sorted(values)


def list_procedure_folders(textos_dir: Path) -> list[str]:
    """List procedure folder slugs under ``textos_dir`` that contain at least one PDF."""
    if not textos_dir.is_dir():
        return []

    seen: set[str] = set()
    folders: list[str] = []
    for path in sorted(textos_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if path.name.lower() in {OTHER_OPTION_VALUE, "otro"}:
            continue
        if not any(path.glob("*.pdf")):
            continue
        canonical = canonical_procedure_id(path.name)
        if canonical in seen:
            continue
        seen.add(canonical)
        folders.append(canonical)
    return folders


def list_scenarios_from_textos(textos_dir: Path) -> list[str]:
    """List procedure ids from subfolders in ``data/textos``."""
    return list_procedure_folders(textos_dir)


def scenario_label(scenario: ProcedureScenario) -> str:
    for _key, label, option in SCENARIO_OPTIONS:
        if option == scenario:
            return label
    if scenario == ProcedureScenario.OTHER:
        return OTHER_OPTION_LABEL
    return scenario.value.replace("_", " ").replace("-", " ")


def procedure_display_label(procedure_id: str, *, textos_dir: Path | None = None) -> str:
    """Human-readable label for a procedure folder slug."""
    canonical = canonical_procedure_id(procedure_id)
    if textos_dir is not None:
        custom = get_procedure_label(textos_dir, canonical)
        if custom:
            return custom
    scenario = FOLDER_TO_SCENARIO.get(canonical)
    if scenario is not None:
        return scenario_label(scenario)
    return canonical.replace("-", " ").replace("_", " ")


def folder_display_label(folder_name: str, *, textos_dir: Path | None = None) -> str:
    """Human-readable label for a `data/textos` folder."""
    return procedure_display_label(normalize_procedure_id(folder_name), textos_dir=textos_dir)


def list_procedure_options_from_disk(textos_dir: Path) -> list[tuple[str, str]]:
    """List dropdown options from folders in ``textos_dir``, always including other."""
    options = [
        (folder, procedure_display_label(folder, textos_dir=textos_dir))
        for folder in list_procedure_folders(textos_dir)
    ]
    options.append((OTHER_OPTION_VALUE, OTHER_OPTION_LABEL))
    return options


def list_admin_procedure_options(textos_dir: Path) -> list[tuple[str, str]]:
    """Admin dropdown: known folders plus Otro."""
    options = [
        (folder, procedure_display_label(folder, textos_dir=textos_dir))
        for folder in list_procedure_folders(textos_dir)
    ]
    options.append((OTHER_OPTION_VALUE, OTHER_OPTION_LABEL))
    return options


def scenario_from_choice(raw: str) -> ProcedureScenario | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned == "6" or cleaned.lower() in {"otro", OTHER_OPTION_VALUE}:
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


def resolve_procedure_selection(
    raw: str,
    *,
    custom_label: str | None = None,
) -> ProcedureSelection:
    """Map a UI selection (folder name, label, or enum value) to a procedure identity."""
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Tipo de procedimiento vacío")

    if cleaned.lower() in {OTHER_OPTION_VALUE, "otro", "6"}:
        label = (custom_label or "").strip() or None
        return ProcedureSelection(
            procedure_id=OTHER_OPTION_VALUE,
            procedure_scenario=ProcedureScenario.OTHER,
            is_other=True,
            custom_label=label,
            uses_general_protocol=True,
        )

    scenario = scenario_from_choice(cleaned)
    if scenario is not None and scenario != ProcedureScenario.OTHER:
        return ProcedureSelection(
            procedure_id=scenario_to_procedure_id(scenario),
            procedure_scenario=scenario,
        )

    procedure_id = normalize_procedure_id(cleaned)
    mapped = FOLDER_TO_SCENARIO.get(procedure_id)
    if mapped is not None:
        return ProcedureSelection(
            procedure_id=scenario_to_procedure_id(mapped),
            procedure_scenario=mapped,
        )

    return ProcedureSelection(
        procedure_id=procedure_id,
        procedure_scenario=ProcedureScenario.OTHER,
        custom_label=cleaned,
        uses_general_protocol=False,
    )


def resolve_procedure_id(raw: str, *, custom_label: str | None = None) -> ProcedureSelection:
    """Alias for ``resolve_procedure_selection``."""
    return resolve_procedure_selection(raw, custom_label=custom_label)
