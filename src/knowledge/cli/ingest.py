"""CLI entry point for batch ingestion."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core.config import get_settings
from knowledge.ingest.pipeline import IngestPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch ingest clinical PDFs into Qdrant.",
    )
    parser.add_argument(
        "--textos-dir",
        type=Path,
        default=None,
        help="Directory containing clinical PDFs (default: TEXTOS_DIR env).",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate the Qdrant collection before ingesting.",
    )
    parser.add_argument(
        "--skip-protocols",
        action="store_true",
        help="Skip post-ingest protocol generation.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    textos_dir = args.textos_dir or settings.textos_dir
    if not textos_dir.exists():
        print(f"Textos directory not found: {textos_dir}", file=sys.stderr)
        return 1

    pipeline = IngestPipeline(settings)
    report = pipeline.ingest_directory(
        textos_dir,
        recreate=args.recreate,
        generate_protocols=not args.skip_protocols,
    )

    print("Ingestion complete")
    print(f"  Indexed documents: {report.indexed_documents}")
    print(f"  Total chunks in store: {report.total_chunks}")
    print(f"  Skipped (no text): {len(report.skipped_no_text)}")
    print(f"  Skipped (duplicates): {len(report.skipped_duplicates)}")
    print(f"  Errors: {len(report.errors)}")

    if report.skipped_no_text:
        print("\nSkipped PDFs without sufficient text:")
        for path in report.skipped_no_text:
            print(f"  - {path}")

    if report.skipped_duplicates:
        print("\nSkipped duplicate PDFs:")
        for path in report.skipped_duplicates:
            print(f"  - {path}")

    if report.errors:
        print("\nErrors:")
        for error in report.errors:
            print(f"  - {error}")
        return 1

    if report.protocol_generation is not None:
        protocol_report = report.protocol_generation
        print(f"  Protocols generated: {len(protocol_report.procedures)}")
        print(f"  General protocol: {protocol_report.general_protocol_path}")
        if protocol_report.errors:
            print(f"  Protocol errors: {len(protocol_report.errors)}")
            for error in protocol_report.errors:
                print(f"    - {error}")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
