"""Hot reload CLI: validate and index a single PDF into Qdrant."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from agent.llm.groq_client import GroqClient
from core.config import get_settings
from core.exceptions import LLMError, PostOpError
from core.models import ProcedureScenario
from core.scenarios import (
    SCENARIO_FOLDER_NAMES,
    SCENARIO_OPTIONS,
    scenario_from_choice,
    scenario_label,
)
from knowledge.ingest.pdf_parser import extract_document_excerpt
from knowledge.ingest.pipeline import IngestPipeline


def _prompt_procedure() -> ProcedureScenario:
    print("Seleccione la categoría de cirugía (obligatorio):")
    for key, label, _scenario in SCENARIO_OPTIONS:
        print(f"  {key}. {label}")
    print("  6. Otro")

    raw = input("Opción: ").strip()
    scenario = scenario_from_choice(raw)
    if scenario is None:
        print(f"Opción inválida: {raw}", file=sys.stderr)
        raise SystemExit(1)
    return scenario


def _prompt_pdf_path() -> Path:
    while True:
        raw = input("Ruta del PDF a indexar: ").strip()
        if not raw:
            print("La ruta es obligatoria.", file=sys.stderr)
            continue
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            print(f"No existe el archivo: {path}", file=sys.stderr)
            continue
        if path.suffix.lower() != ".pdf":
            print("Solo se admiten archivos PDF.", file=sys.stderr)
            continue
        return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and hot-reload a clinical PDF into Qdrant.",
    )
    parser.add_argument(
        "--scenario",
        choices=[scenario.value for _, _, scenario in SCENARIO_OPTIONS] + ["otro"],
        default=None,
        help="Surgery category (required unless prompted interactively).",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Path to the PDF file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()

    scenario = ProcedureScenario(args.scenario) if args.scenario else _prompt_procedure()
    pdf_path = args.pdf.resolve() if args.pdf else _prompt_pdf_path()

    excerpt = extract_document_excerpt(
        pdf_path,
        max_chars=settings.document_validation_excerpt_chars,
    )
    if not excerpt:
        print("El PDF no contiene texto suficiente para validar.", file=sys.stderr)
        return 1

    try:
        llm = GroqClient(settings)
        matches, message = llm.validate_document_category(
            document_excerpt=excerpt,
            procedure_scenario=scenario,
        )
    except LLMError as exc:
        print(f"Error de validación LLM: {exc}", file=sys.stderr)
        return 1

    if not matches:
        print(f"ALERTA: {message}", file=sys.stderr)
        return 1

    target_dir = settings.textos_dir / SCENARIO_FOLDER_NAMES[scenario]
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / pdf_path.name
    if pdf_path != destination:
        shutil.copy2(pdf_path, destination)

    try:
        pipeline = IngestPipeline(settings)
        document = pipeline.index_document(destination, procedure_scenario=scenario)
    except PostOpError as exc:
        print(f"Error al indexar: {exc}", file=sys.stderr)
        return 1

    print("Documento validado e indexado correctamente.")
    print(f"  Categoría: {scenario_label(scenario)}")
    print(f"  Archivo: {document.file_name}")
    print(f"  source_id: {document.source_id}")
    if message:
        print(f"  Validación: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
