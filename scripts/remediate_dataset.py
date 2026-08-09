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
LEGACY_CERVICAL_FOLDER = "breast_cancer"
CERVICAL_FOLDER = SCENARIO_FOLDER_NAMES[ProcedureScenario.CERVICAL_CANCER]
OTHER_FOLDER = SCENARIO_FOLDER_NAMES[ProcedureScenario.OTHER]

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


# PDFs flagged by EDA as misclassified (keyword heuristic). cervical-es-patient stays
# in cuello uterino after the folder rename — content is a cervical patient guide.
RECLASSIFICATIONS: tuple[PdfMove, ...] = (
    PdfMove(
        "Appendicitis",
        _ESTABLISHING_PDF,
        OTHER_FOLDER,
        "Contenido genérico de seguimiento; no encaja en ningún escenario clínico principal.",
    ),
    PdfMove(
        "Appendicitis",
        _REVISION_PDF,
        OTHER_FOLDER,
        "PDF escaneado sin texto extraíble; requiere OCR.",
    ),
    PdfMove(
        "cholecystitis",
        _CUIDADO_GI_PDF,
        OTHER_FOLDER,
        "Guía GI general, no específica de colecistitis.",
    ),
    PdfMove(
        "cholecystitis",
        _NURSING_REVIEW_PDF,
        OTHER_FOLDER,
        "Revisión de enfermería transversal; clasificado como Otro por el EDA.",
    ),
)


def rename_cervical_folder(*, dry_run: bool) -> bool:
    source = TEXTOS_DIR / LEGACY_CERVICAL_FOLDER
    target = TEXTOS_DIR / CERVICAL_FOLDER
    if target.exists():
        logger.info("Carpeta destino ya existe: %s", target)
        return False
    if not source.exists():
        logger.info("Carpeta legacy no encontrada (ya renombrada): %s", source)
        return False
    logger.info("Renombrar %s → %s", source.name, target.name)
    if not dry_run:
        source.rename(target)
    return True


def move_misclassified(*, dry_run: bool) -> list[PdfMove]:
    applied: list[PdfMove] = []
    other_dir = TEXTOS_DIR / OTHER_FOLDER
    if not dry_run:
        other_dir.mkdir(exist_ok=True)

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
            shutil.move(str(source), str(destination))
        applied.append(move)
    return applied


def validate_layout() -> list[str]:
    issues: list[str] = []
    if (TEXTOS_DIR / LEGACY_CERVICAL_FOLDER).exists():
        issues.append(f"Carpeta legacy '{LEGACY_CERVICAL_FOLDER}' aún presente.")
    cervical = TEXTOS_DIR / CERVICAL_FOLDER
    if not cervical.exists():
        issues.append(f"Falta carpeta '{CERVICAL_FOLDER}'.")
    other = TEXTOS_DIR / OTHER_FOLDER
    if not other.exists():
        issues.append(f"Falta carpeta '{OTHER_FOLDER}'.")
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

    renamed = rename_cervical_folder(dry_run=args.dry_run)
    moves = move_misclassified(dry_run=args.dry_run)

    if args.dry_run:
        logger.info("Dry run: %s rename, %s moves planned.", int(renamed), len(moves))
        return

    issues = validate_layout()
    if issues:
        for issue in issues:
            logger.error(issue)
        raise SystemExit(1)

    logger.info(
        "Remediación completada: carpeta renombrada=%s, PDFs movidos=%s.",
        renamed,
        len(moves),
    )


if __name__ == "__main__":
    main()
