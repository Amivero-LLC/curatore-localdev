#!/usr/bin/env bash
# ============================================================================
# Curatore Local Dev — View Service Logs
# ============================================================================
# Usage:
#   ./scripts/dev-logs.sh              # All backend logs
#   ./scripts/dev-logs.sh backend      # Backend API only
#   ./scripts/dev-logs.sh worker       # All worker logs (documents + general)
#   ./scripts/dev-logs.sh frontend     # Frontend only
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
    # Show all worker pool logs combined
    docker logs -f curatore-worker-documents curatore-worker-general 2>/dev/null
    ;;
  worker-documents)
    docker logs -f curatore-worker-documents
    ;;
  worker-general)
    docker logs -f curatore-worker-general
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
  all)
    docker logs -f curatore-backend curatore-worker-documents curatore-worker-general curatore-beat curatore-redis curatore-minio curatore-frontend curatore-document-service curatore-playwright curatore-mcp 2>/dev/null
    ;;
  *)
    echo "Usage: dev-logs.sh [backend|worker|worker-documents|worker-general|beat|frontend|mcp|document-service|playwright|minio|redis|postgres|all]"
    echo ""
    echo "Without arguments, shows backend logs."
    echo ""
    cd "${ROOT}/curatore-backend" && docker compose logs -f --tail 50
    ;;
esac
