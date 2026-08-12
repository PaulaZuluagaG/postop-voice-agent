"""Persist Spanish display labels for custom procedure folders under ``textos/``."""

from __future__ import annotations

import json
from pathlib import Path

LABELS_FILENAME = "procedure_labels.json"


def _canonical_procedure_id(procedure_id: str) -> str:
    from core.scenarios import canonical_procedure_id

    return canonical_procedure_id(procedure_id)


def load_procedure_labels(textos_dir: Path) -> dict[str, str]:
    path = textos_dir / LABELS_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        _canonical_procedure_id(str(key)): str(value).strip()
        for key, value in payload.items()
        if str(value).strip()
    }


def get_procedure_label(textos_dir: Path, procedure_id: str) -> str | None:
    labels = load_procedure_labels(textos_dir)
    return labels.get(_canonical_procedure_id(procedure_id))


def save_procedure_label(textos_dir: Path, procedure_id: str, label_es: str) -> None:
    cleaned = label_es.strip()
    if not cleaned:
        return
    textos_dir.mkdir(parents=True, exist_ok=True)
    labels = load_procedure_labels(textos_dir)
    labels[_canonical_procedure_id(procedure_id)] = cleaned
    path = textos_dir / LABELS_FILENAME
    path.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_procedure_label(textos_dir: Path, procedure_id: str) -> None:
    labels = load_procedure_labels(textos_dir)
    key = _canonical_procedure_id(procedure_id)
    if key not in labels:
        return
    del labels[key]
    path = textos_dir / LABELS_FILENAME
    if not labels:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
