"""Load post-operative protocols for agent runtime."""

from __future__ import annotations

import json
from pathlib import Path

from core.config import Settings, get_settings
from core.models import ProcedureScenario
from core.scenarios import OTHER_OPTION_VALUE, canonical_procedure_id, scenario_to_procedure_id
from knowledge.protocol.models import PostOpProtocol

GENERAL_PROTOCOL_DIR = "general"
GENERAL_PROTOCOL_FILENAME = "protocol.json"


def _protocol_candidates(procedure_id: str, protocol_dir: Path) -> list[Path]:
    """Return candidate protocol paths for the canonical folder slug."""
    canonical = canonical_procedure_id(procedure_id)
    return [protocol_dir / canonical / GENERAL_PROTOCOL_FILENAME]


def load_general_protocol(*, settings: Settings | None = None) -> PostOpProtocol:
    settings = settings or get_settings()
    path = settings.protocol_dir / GENERAL_PROTOCOL_DIR / GENERAL_PROTOCOL_FILENAME
    if not path.is_file():
        bundled = Path(__file__).resolve().parent / "general_protocol.json"
        if bundled.is_file():
            path = bundled
        else:
            raise FileNotFoundError(f"General protocol not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return PostOpProtocol.model_validate(data)


def load_protocol_for_procedure(
    procedure_id: str,
    *,
    settings: Settings | None = None,
    uses_general_protocol: bool = False,
) -> tuple[PostOpProtocol, str]:
    """Load the active protocol and return ``(protocol, protocol_key)``."""
    settings = settings or get_settings()
    normalized = procedure_id.strip().lower()

    if uses_general_protocol or normalized in {OTHER_OPTION_VALUE, "otro"}:
        return load_general_protocol(settings=settings), GENERAL_PROTOCOL_DIR

    for candidate in _protocol_candidates(normalized, settings.protocol_dir):
        if candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            protocol = PostOpProtocol.model_validate(data)
            return protocol, candidate.parent.name

    return load_general_protocol(settings=settings), GENERAL_PROTOCOL_DIR


def load_protocol_for_scenario(
    scenario: ProcedureScenario,
    *,
    settings: Settings | None = None,
    uses_general_protocol: bool = False,
) -> tuple[PostOpProtocol, str]:
    procedure_id = scenario_to_procedure_id(scenario)
    return load_protocol_for_procedure(
        procedure_id,
        settings=settings,
        uses_general_protocol=uses_general_protocol or scenario == ProcedureScenario.OTHER,
    )
