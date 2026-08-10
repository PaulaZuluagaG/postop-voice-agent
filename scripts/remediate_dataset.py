"""Apply EDA remediation: folder rename, PDF reclassification, and validation."""

from __future__ import annotations

import argparse
import logging
import shutil
from dataclasses import dataclass

from core.config import get_settings
from core.models import ProcedureScenario
from core.scenarios import SCENARIO_FOLDER_NAMES

logger = logging.getLogger(__name__)

TEXTOS_DIR = get_settings().textos_dir.resolve()
APPENDICITIS_FOLDER = SCENARIO_FOLDER_NAMES[ProcedureScenario.APPENDICITIS]
CHOLECYSTITIS_FOLDER = SCENARIO_FOLDER_NAMES[ProcedureScenario.CHOLECYSTITIS]

_ESTABLISHING_PDF = (
    "Establishing the need for clinical follow-up after emergency appendicectomy "
    "in the modern era_ Retrospective case series of 145 patients.pdf"
)
_REVISION_PDF = (
    "REVISIÓN DE LA LITERATURA SOBRE LAAPENDICITIS AGUDA PEDIATRICA "
    "NO ESPECIFICADA EN EL PERI000 2000-2021.pdf"
)
_CUIDADO_GI_PDF = (
    "CUIDADO ESTANDARIZADO EN EL PACIENTE QUIRURGICO CON ALTERACIONES "
    "EN LA FUNCION GASTROINTESTINAL.pdf"
)
_NURSING_REVIEW_PDF = (
    "Postoperative care for patients undergoing cholecystectomy- "
    "A comprehensive nursing review.pdf"
)


@dataclass(frozen=True)
class PdfMove:
    source_folder: str
    file_name: str
    target_folder: str
    reason: str


# Reclassify former Otro documents back into their closest procedure folders.
RECLASSIFICATIONS: tuple[PdfMove, ...] = (
    PdfMove(
        "other",
        _ESTABLISHING_PDF,
        APPENDICITIS_FOLDER,
        "Seguimiento post-apendicectomía; encaja en appendicitis.",
    ),
    PdfMove(
        "other",
        _REVISION_PDF,
        APPENDICITIS_FOLDER,
        "Revisión de literatura sobre apendicitis pediátrica.",
    ),
    PdfMove(
        "other",
        _CUIDADO_GI_PDF,
        CHOLECYSTITIS_FOLDER,
        "Cuidado GI postoperatorio; mejor encaje en colecistitis.",
    ),
    PdfMove(
        "other",
        _NURSING_REVIEW_PDF,
        CHOLECYSTITIS_FOLDER,
        "Revisión de cuidados post-colecistectomía.",
    ),
)

FOLDER_RENAMES: tuple[tuple[str, str], ...] = (
    ("Appendicitis", "appendicitis"),
    ("cuello uterino", "cervical-cancer"),
    ("colorectal cancer", "colorectal-cancer"),
    ("total joint replacement", "total-joint-replacement"),
    ("Otro", "other"),
)


def rename_folders(*, dry_run: bool) -> int:
    renamed = 0
    for source_name, target_name in FOLDER_RENAMES:
        source = TEXTOS_DIR / source_name
        target = TEXTOS_DIR / target_name
        if not source.exists():
            continue
        if target.exists():
            logger.info("Carpeta destino ya existe: %s", target)
            continue
        logger.info("Renombrar %s → %s", source.name, target.name)
        if not dry_run:
            source.rename(target)
        renamed += 1
    return renamed


def move_misclassified(*, dry_run: bool) -> list[PdfMove]:
    applied: list[PdfMove] = []
    for move in RECLASSIFICATIONS:
        source = TEXTOS_DIR / move.source_folder / move.file_name
        destination = TEXTOS_DIR / move.target_folder / move.file_name
        if not source.exists():
            if destination.exists():
                logger.info("Ya movido: %s", move.file_name)
                applied.append(move)
            else:
                logger.warning("No encontrado: %s", source)
            continue
        logger.info("Mover %s → %s (%s)", source.name, move.target_folder, move.reason)
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        applied.append(move)
    return applied


def validate_layout() -> list[str]:
    issues: list[str] = []
    for _source_name, target_name in FOLDER_RENAMES:
        if (TEXTOS_DIR / _source_name).exists():
            issues.append(f"Carpeta legacy '{_source_name}' aún presente.")
        if target_name != "other" and not (TEXTOS_DIR / target_name).exists():
            issues.append(f"Falta carpeta '{target_name}'.")
    other_dir = TEXTOS_DIR / "other"
    if other_dir.exists() and any(other_dir.glob("*.pdf")):
        issues.append("La carpeta 'other' aún contiene PDFs sin reclasificar.")
    for move in RECLASSIFICATIONS:
        if (TEXTOS_DIR / move.source_folder / move.file_name).exists():
            issues.append(f"PDF sin mover: {move.file_name}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply EDA dataset remediation.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show actions without changing files."
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    moves = move_misclassified(dry_run=args.dry_run)
    renamed = rename_folders(dry_run=args.dry_run)

    if args.dry_run:
        logger.info("Dry run: %s renames, %s moves planned.", renamed, len(moves))
        return

    issues = validate_layout()
    if issues:
        for issue in issues:
            logger.error(issue)
        raise SystemExit(1)

    logger.info(
        "Remediación completada: carpetas renombradas=%s, PDFs movidos=%s.",
        renamed,
        len(moves),
    )


if __name__ == "__main__":
    main()
