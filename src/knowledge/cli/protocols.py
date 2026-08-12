"""CLI entry point for protocol generation."""

from __future__ import annotations

import argparse
import logging
import sys

from core.config import get_settings
from core.exceptions import LLMError
from knowledge.ingest.pipeline import IngestPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate post-operative protocols from indexed Qdrant knowledge.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate protocols even if they already exist on disk.",
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
    pipeline = IngestPipeline(settings)
    try:
        report = pipeline.generate_protocols(force=args.force)
    except LLMError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    protocol_report = report.protocol_generation
    if protocol_report is None:
        print("No protocol generation report produced.", file=sys.stderr)
        return 1

    print("Protocol generation complete")
    print(f"  General protocol: {protocol_report.general_protocol_path}")
    print(f"  Procedures generated: {len(protocol_report.procedures)}")
    print(f"  Procedures skipped: {len(protocol_report.skipped_procedures)}")
    print(f"  Errors: {len(protocol_report.errors)}")

    for skipped in protocol_report.skipped_procedures:
        print(f"  - skipped (exists): {skipped}")

    for item in protocol_report.procedures:
        print(
            f"  - {item.procedure_scenario}: {item.chunks_retrieved} chunks, "
            f"{item.qdrant_points_updated} Qdrant points -> {item.protocol_path}"
        )

    if protocol_report.errors:
        print("\nErrors:")
        for error in protocol_report.errors:
            print(f"  - {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
