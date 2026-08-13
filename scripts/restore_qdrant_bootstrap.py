"""Restore Qdrant collection from bootstrap snapshot when the volume is empty."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from core.config import get_settings


def _collection_point_count(base_url: str, collection: str) -> int | None:
    try:
        response = httpx.get(f"{base_url}/collections/{collection}", timeout=10.0)
        if response.status_code == 404:
            return 0
        response.raise_for_status()
        payload = response.json()
        return int(payload["result"]["points_count"])
    except Exception:
        return None


def _find_snapshot_file(bootstrap_dir: Path) -> Path | None:
    for pattern in ("*.snapshot", "*.tar", "*.tar.gz"):
        matches = sorted(bootstrap_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def restore_if_needed(*, bootstrap_dir: Path | None = None) -> int:
    settings = get_settings()
    bootstrap = bootstrap_dir or (Path(__file__).resolve().parent.parent / "bootstrap" / "qdrant")
    snapshot = _find_snapshot_file(bootstrap)
    if snapshot is None:
        print("No Qdrant bootstrap snapshot found; skipping restore.")
        return 0

    base_url = settings.qdrant_url.rstrip("/")
    existing = _collection_point_count(base_url, settings.qdrant_collection)
    if existing is None:
        print("Qdrant not reachable; skipping bootstrap restore.", file=sys.stderr)
        return 1
    if existing > 0:
        print(f"Qdrant already has {existing} points; skipping bootstrap restore.")
        return 0

    print(f"Restoring Qdrant collection from {snapshot.name} ...")
    with snapshot.open("rb") as handle:
        response = httpx.post(
            f"{base_url}/collections/{settings.qdrant_collection}/snapshots/upload"
            f"?wait=true&priority=snapshot",
            files={"snapshot": (snapshot.name, handle, "application/octet-stream")},
            timeout=300.0,
        )
    if response.status_code not in (200, 201):
        print(
            f"Snapshot restore failed: {response.status_code} {response.text}",
            file=sys.stderr,
        )
        return 1

    restored = _collection_point_count(base_url, settings.qdrant_collection) or 0
    print(f"Qdrant restore complete ({restored} points).")
    return 0


def main() -> int:
    return restore_if_needed()


if __name__ == "__main__":
    raise SystemExit(main())
