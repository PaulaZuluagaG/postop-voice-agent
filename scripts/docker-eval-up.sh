#!/usr/bin/env bash
# Levantamiento completo para evaluación (objetivo: ≤15 min en hardware típico).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

if [[ ! -f .env ]]; then
  echo "ERROR: falta .env — ejecute: cp .env.example .env y configure las API keys." >&2
  echo "       Defaults en src/core/config.py; plantilla: uv run postop-config-example" >&2
  exit 1
fi

START_TS=$(date +%s)

_seed_host_protocols() {
  if [[ ! -f storage/protocols/general/protocol.json ]] \
    && [[ -d bootstrap/protocols/general ]]; then
    echo "==> Seeding storage/protocols from bootstrap/ ..."
    mkdir -p storage/protocols
    cp -a bootstrap/protocols/. storage/protocols/
  fi
}

echo "==> [1/4] Build imágenes core (backend compartido + frontends; sin Jupyter)..."
docker compose build backend-api frontend-paciente frontend-admin

echo "==> [2/4] Levantar stack..."
_seed_host_protocols
docker compose up -d

echo "==> Esperando servicios healthy..."
deadline=$((SECONDS + 180))
while (( SECONDS < deadline )); do
  if curl -sf http://localhost:8000/openapi.json >/dev/null \
    && curl -sf http://localhost:7860/status >/dev/null \
    && curl -sf http://localhost:3000 >/dev/null \
    && curl -sf http://localhost:8080 >/dev/null; then
    break
  fi
  sleep 3
done

echo "==> [3/4] Bootstrap Qdrant (snapshot) o ingesta fallback..."
docker compose exec -T backend-api python scripts/restore_qdrant_bootstrap.py || true

if ! curl -sf http://localhost:7860/api/readiness >/dev/null; then
  echo "==> Snapshot ausente o vacío: ingesta PDFs (--skip-protocols, protocolos ya en bootstrap/) ..."
  docker compose --profile init run --rm ingest-init postop-ingest --recreate --skip-protocols
fi

echo "==> [4/4] Verificando readiness de voz..."
if curl -sf http://localhost:7860/api/readiness >/dev/null; then
  echo "OK: agente listo para llamadas."
else
  echo "WARN: /api/readiness aún no responde 200. Revise logs: docker compose logs backend-voice backend-api" >&2
fi

ELAPSED=$(( $(date +%s) - START_TS ))
MIN=$(( ELAPSED / 60 ))
SEC=$(( ELAPSED % 60 ))
echo ""
echo "Tiempo total: ${MIN}m ${SEC}s"
echo ""
echo "URLs:"
echo "  Paciente:  http://localhost:3000"
echo "  Admin:     http://localhost:8080"
echo "  Voice API: http://localhost:7860/api/readiness"
echo ""
echo "Jupyter (opcional): docker compose --profile analysis up -d jupyter-notebook"
