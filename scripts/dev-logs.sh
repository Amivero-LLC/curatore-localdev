#!/usr/bin/env bash
# ============================================================================
# Curatore Local Dev — View Service Logs
# ============================================================================
# Usage:
#   ./scripts/dev-logs.sh              # All backend logs
#   ./scripts/dev-logs.sh backend      # Backend API only
#   ./scripts/dev-logs.sh worker       # Celery worker only
#   ./scripts/dev-logs.sh frontend     # Frontend only
#   ./scripts/dev-logs.sh docling      # Docling engine
#   ./scripts/dev-logs.sh all          # All containers
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SERVICE="${1:-}"

case "${SERVICE}" in
  backend)
    docker logs -f curatore-backend
    ;;
  worker)
    docker logs -f curatore-worker
    ;;
  beat)
    docker logs -f curatore-beat
    ;;
  frontend)
    docker logs -f curatore-frontend
    ;;
  mcp)
    docker logs -f curatore-mcp
    ;;
  document-service|extraction)
    docker logs -f curatore-document-service
    ;;
  playwright)
    docker logs -f curatore-playwright
    ;;
  minio)
    docker logs -f curatore-minio
    ;;
  redis)
    docker logs -f curatore-redis
    ;;
  postgres)
    docker logs -f curatore-postgres
    ;;
  docling)
    docker logs -f curatore-docling
    ;;
  all)
    docker logs -f curatore-backend curatore-worker curatore-beat curatore-redis curatore-minio curatore-frontend curatore-document-service curatore-playwright curatore-mcp curatore-docling 2>/dev/null
    ;;
  *)
    echo "Usage: dev-logs.sh [backend|worker|beat|frontend|mcp|document-service|playwright|docling|minio|redis|postgres|all]"
    echo ""
    echo "Without arguments, shows backend logs."
    echo ""
    cd "${ROOT}/curatore-backend" && docker compose logs -f --tail 50
    ;;
esac
