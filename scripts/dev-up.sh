#!/usr/bin/env bash
# ============================================================================
# Curatore Local Dev — Start All Services
# ============================================================================
# Creates the shared Docker network and starts services in dependency order.
#
# Usage:
#   ./scripts/dev-up.sh                  # Core services only
#   ./scripts/dev-up.sh --all            # All services including optional ones
#   ./scripts/dev-up.sh --with-postgres  # Include PostgreSQL
#   ./scripts/dev-up.sh --with-docling   # Include Docling engine
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Parse flags
WITH_POSTGRES=false
WITH_DOCLING=false
WITH_ALL=false

for arg in "$@"; do
  case "$arg" in
    --with-postgres) WITH_POSTGRES=true ;;
    --with-docling)  WITH_DOCLING=true ;;
    --all)           WITH_ALL=true ;;
  esac
done

if [[ "$WITH_ALL" == "true" ]]; then
  WITH_POSTGRES=true
  WITH_DOCLING=true
fi

# Read feature flags from backend .env if present
if [[ -f "${ROOT}/curatore-backend/.env" ]]; then
  _env_postgres="$(grep -E '^ENABLE_POSTGRES_SERVICE=' "${ROOT}/curatore-backend/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '"' | tr '[:upper:]' '[:lower:]')"
  if [[ "$_env_postgres" == "true" ]]; then
    WITH_POSTGRES=true
  fi
fi

echo "============================================"
echo "  Curatore Local Development Environment"
echo "============================================"
echo ""

# ---- 1. Create shared Docker network ----
echo "1. Creating shared Docker network..."
docker network create curatore-network 2>/dev/null && echo "   Created curatore-network" || echo "   curatore-network already exists"
echo ""

# ---- 2. Start backend + Redis + MinIO (+ optional Postgres, Docling) ----
echo "2. Starting Backend (API + Worker + Beat + Redis + MinIO)..."
cd "${ROOT}/curatore-backend"

PROFILES=""
if [[ "$WITH_POSTGRES" == "true" ]]; then
  PROFILES="${PROFILES} --profile postgres"
  echo "   Including PostgreSQL"
fi
if [[ "$WITH_DOCLING" == "true" ]]; then
  PROFILES="${PROFILES} --profile docling"
  echo "   Including Docling"
fi

docker compose ${PROFILES} up -d --build
echo ""

# ---- 3. Start Document Service ----
echo "3. Starting Document Service..."
cd "${ROOT}/curatore-document-service"
docker compose up -d
echo ""

# ---- 4. Start Playwright Service ----
echo "4. Starting Playwright Service..."
cd "${ROOT}/curatore-playwright-service"
docker compose up -d
echo ""

# ---- 5. Start Frontend ----
echo "5. Starting Frontend..."
cd "${ROOT}/curatore-frontend"
docker compose up -d
echo ""

# ---- 6. Start MCP Gateway ----
echo "6. Starting MCP Gateway..."
cd "${ROOT}/curatore-mcp-service"
docker compose up -d
echo ""

# ---- 7. Initialize storage buckets ----
echo "7. Initializing storage buckets..."
sleep 5  # Wait for backend to start
"${ROOT}/curatore-backend/scripts/init_storage.sh" 2>/dev/null || {
  echo "   Storage init deferred — backend may still be starting."
  echo "   Run manually: ${ROOT}/curatore-backend/scripts/init_storage.sh"
}
echo ""

# ---- Summary ----
echo "============================================"
echo "  All Services Started"
echo "============================================"
echo ""
echo "  Frontend:         http://localhost:3000"
echo "  Backend API:      http://localhost:8000"
echo "  API Docs:         http://localhost:8000/docs"
echo "  Document Service: http://localhost:8010"
echo "  Playwright:       http://localhost:8011"
echo "  MCP Gateway:      http://localhost:8020"
echo "  MinIO Console:    http://localhost:9001"
echo "  Redis:            localhost:6379"
if [[ "$WITH_POSTGRES" == "true" ]]; then
echo "  PostgreSQL:       localhost:5432"
fi
echo ""
echo "  View logs: ./scripts/dev-logs.sh"
echo "  Stop all:  ./scripts/dev-down.sh"
echo "============================================"
