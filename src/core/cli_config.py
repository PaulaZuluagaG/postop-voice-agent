"""CLI helpers for centralized configuration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import get_settings
from core.env_example import format_effective_settings, write_env_example
from core.paths import project_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gestión de configuración centralizada (defaults en core/config.py).",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Genera plantilla reducida (solo secretos y variables de Docker).",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Muestra la configuración efectiva (defaults + .env), sin escribir archivos.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root() / ".env.example",
        help="Ruta de salida para la plantilla (default: .env.example en la raíz).",
    )
    args = parser.parse_args(argv)

    if args.show:
        get_settings.cache_clear()
        sys.stdout.write(format_effective_settings(get_settings()))
        return 0

    write_env_example(args.output, minimal=args.minimal)
    mode = "mínima" if args.minimal else "completa"
    print(f"Plantilla {mode} escrita en {args.output}")
    return 0
