#!/usr/bin/env bash
# Genera artefactos bootstrap/ (protocolos + snapshot Qdrant) para evaluación rápida.
#
# Por defecto ingesta en LOCAL (uv) — mucho más rápido que Docker en Mac.
# Usa --docker si necesitas reproducir el entorno del contenedor.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export DOCKER_BUILDKIT=1

INGEST_MODE="local"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker) INGEST_MODE="docker"; shift ;;
    --local) INGEST_MODE="local"; shift ;;
    -h|--help)
      echo "Usage: $0 [--local|--docker]"
      echo "  --local   (default) ingest with uv on host; Qdrant in Docker"
      echo "  --docker  ingest inside ingest-init container (slow on Mac)"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -f .env ]]; then
  echo "ERROR: falta .env" >&2
  exit 1
fi

COLLECTION="${QDRANT_COLLECTION:-postop_clinical_knowledge}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
TEXTOS_DIR="${TEXTOS_DIR:-data/textos}"

echo "==> [1/4] Verificar protocolos bootstrap/ ..."
mkdir -p bootstrap/protocols
if compgen -G "bootstrap/protocols/*/protocol.json" > /dev/null; then
  echo "    bootstrap/protocols OK"
else
  echo "ERROR: bootstrap/protocols vacío. Restaure los JSON antes de continuar." >&2
  exit 1
fi

echo "==> [2/4] Levantar Qdrant ..."
docker compose up -d qdrant-db
echo "    Esperando Qdrant healthy..."
deadline=$((SECONDS + 60))
while (( SECONDS < deadline )); do
  if curl -sf "${QDRANT_URL}/collections" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "==> [3/4] Ingesta completa (genera índice Qdrant) — modo: ${INGEST_MODE} ..."

_run_local_ingest() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv no encontrado. Instale uv o use --docker." >&2
    exit 1
  fi
  if [[ ! -d "${TEXTOS_DIR}" ]]; then
    echo "ERROR: TEXTOS_DIR no existe: ${TEXTOS_DIR}" >&2
    exit 1
  fi
  echo "    PDFs en ${TEXTOS_DIR}: $(find "${TEXTOS_DIR}" -name '*.pdf' | wc -l | tr -d ' ')"
  echo "    (Progreso: [N/total] por PDF — puede tardar 10–20 min en CPU local)"
  QDRANT_HOST=localhost \
  QDRANT_PORT=6333 \
  TEXTOS_DIR="${TEXTOS_DIR}" \
  OCR_ENABLED=false \
  EMBEDDING_BATCH_SIZE=64 \
  PROTOCOL_GENERATION_DELAY_SECONDS=0 \
    uv run postop-ingest --recreate --skip-protocols --verbose
}

_run_docker_ingest() {
  echo "    ADVERTENCIA: ingesta en Docker puede tardar 1–3 h en Mac (CPU emulado/limitado)."
  docker compose --profile init run --rm ingest-init postop-ingest --recreate --skip-protocols --verbose
}

case "${INGEST_MODE}" in
  local) _run_local_ingest ;;
  docker) _run_docker_ingest ;;
esac

POINTS="$(curl -sf "${QDRANT_URL}/collections/${COLLECTION}" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['points_count'])")"
echo "    Qdrant indexado: ${POINTS} points"
if [[ "${POINTS}" -lt 100 ]]; then
  echo "ERROR: índice demasiado pequeño (${POINTS} points). Revise logs de ingesta." >&2
  exit 1
fi

echo "==> [4/4] Exportar snapshot Qdrant -> bootstrap/qdrant/ ..."
mkdir -p bootstrap/qdrant
# Remove stale snapshots so restore picks the latest only.
find bootstrap/qdrant -maxdepth 1 \( -name '*.snapshot' -o -name '*.tar' -o -name '*.tar.gz' \) -delete 2>/dev/null || true
SNAPSHOT_NAME="$(curl -sf -X POST "${QDRANT_URL}/collections/${COLLECTION}/snapshots" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['name'])")"
curl -sf "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${SNAPSHOT_NAME}" \
  -o "bootstrap/qdrant/${SNAPSHOT_NAME}"

SNAPSHOT_SIZE="$(du -h "bootstrap/qdrant/${SNAPSHOT_NAME}" | cut -f1)"
echo ""
echo "Bootstrap listo:"
echo "  bootstrap/protocols/"
echo "  bootstrap/qdrant/${SNAPSHOT_NAME} (${SNAPSHOT_SIZE})"
echo ""
echo "Siguiente: commitea bootstrap/qdrant/ y ejecuta ./scripts/docker-eval-up.sh (con down -v para probar frío)."
