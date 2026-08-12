"""Project root resolution for path-independent configuration."""

from functools import lru_cache
from pathlib import Path


@lru_cache
def project_root() -> Path:
    """Locate repository root by walking up from this module for pyproject.toml."""
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


def resolve_project_path(value: str | Path) -> Path:
    """Resolve a path relative to the project root when not absolute."""
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root() / path
