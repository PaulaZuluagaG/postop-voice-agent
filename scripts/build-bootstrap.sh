#!/usr/bin/env bash
# Genera artefactos bootstrap/ (protocolos + snapshot Qdrant) para evaluación rápida.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export DOCKER_BUILDKIT=1

if [[ ! -f .env ]]; then
  echo "ERROR: falta .env" >&2
  exit 1
fi

COLLECTION="${QDRANT_COLLECTION:-postop_clinical_knowledge}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

echo "==> [1/4] Sincronizar protocolos bootstrap/ ..."
mkdir -p bootstrap/protocols
if compgen -G "bootstrap/protocols/*/protocol.json" > /dev/null; then
  echo "    bootstrap/protocols ya contiene protocol.json"
else
  echo "ERROR: bootstrap/protocols vacío. Restaure los JSON antes de continuar." >&2
  exit 1
fi

echo "==> [2/4] Levantar Qdrant ..."
docker compose up -d qdrant-db

echo "==> [3/4] Ingesta completa (genera índice Qdrant) ..."
docker compose --profile init run --rm ingest-init postop-ingest --recreate --skip-protocols

echo "==> [4/4] Exportar snapshot Qdrant -> bootstrap/qdrant/ ..."
mkdir -p bootstrap/qdrant
SNAPSHOT_NAME="$(curl -sf -X POST "${QDRANT_URL}/collections/${COLLECTION}/snapshots" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['name'])")"
curl -sf "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${SNAPSHOT_NAME}" \
  -o "bootstrap/qdrant/${SNAPSHOT_NAME}"

echo ""
echo "Bootstrap listo:"
echo "  bootstrap/protocols/"
echo "  bootstrap/qdrant/${SNAPSHOT_NAME}"
echo ""
echo "Commitea bootstrap/ y reconstruye la imagen backend."
