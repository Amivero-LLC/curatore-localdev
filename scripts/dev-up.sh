#!/usr/bin/env bash
# ============================================================================
# Curatore Local Dev — Start All Services
# ============================================================================
# Creates the shared Docker network and starts services in dependency order.
#
# Usage:
#   ./scripts/dev-up.sh                      # Core services only
#   ./scripts/dev-up.sh --all                # All services including optional ones
#   ./scripts/dev-up.sh --with-postgres      # Include PostgreSQL
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Parse flags
WITH_POSTGRES=false
WITH_ALL=false

for arg in "$@"; do
  case "$arg" in
    --with-postgres)    WITH_POSTGRES=true ;;
    --all)              WITH_ALL=true ;;
  esac
done

if [[ "$WITH_ALL" == "true" ]]; then
  WITH_POSTGRES=true
fi

# Read feature flags from root .env if present
if [[ -f "${ROOT}/.env" ]]; then
  _env_postgres="$(grep -E '^ENABLE_POSTGRES_SERVICE=' "${ROOT}/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '"' | tr '[:upper:]' '[:lower:]')"
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

# ---- 2. Start backend + Redis + MinIO (+ optional Postgres) ----
echo "2. Starting Backend (API + Worker + Beat + Redis + MinIO)..."
cd "${ROOT}/curatore-backend"

BACKEND_PROFILES=""
if [[ "$WITH_POSTGRES" == "true" ]]; then
  BACKEND_PROFILES="${BACKEND_PROFILES} --profile postgres"
  echo "   Including PostgreSQL"
fi

docker compose ${BACKEND_PROFILES} up -d --build
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

# ---- 7. Wait for frontend readiness ----
echo "7. Waiting for frontend to compile..."
FRONTEND_READY=false
for i in $(seq 1 60); do
  if curl -sf -o /dev/null http://localhost:3000 2>/dev/null; then
    FRONTEND_READY=true
    echo "   Frontend ready (${i}s)"
    break
  fi
  sleep 5
done

if [[ "$FRONTEND_READY" == "false" ]]; then
  echo "   WARNING: Frontend did not become ready within 300s."
  echo "   It may still be compiling — check ./scripts/dev-logs.sh frontend"
fi
echo ""

# ---- 8. Initialize storage buckets ----
echo "8. Initializing storage buckets..."
echo "   Waiting for backend readiness..."
READY=false
for i in $(seq 1 60); do
  if curl -sf http://localhost:8000/api/v1/admin/system/health/ready >/dev/null 2>&1; then
    READY=true
    echo "   Backend ready (${i}s)"
    break
  fi
  sleep 5
done

if [[ "$READY" == "true" ]]; then
  "${ROOT}/curatore-backend/scripts/init_storage.sh" || {
    echo ""
    echo "   ERROR: Storage initialization failed."
    echo "   Check backend logs: ./scripts/dev-logs.sh"
    echo "   Retry manually: ${ROOT}/curatore-backend/scripts/init_storage.sh"
  }
else
  echo "   WARNING: Backend did not become ready within 300s."
  echo "   Storage init skipped — run manually after backend starts:"
  echo "     ${ROOT}/curatore-backend/scripts/init_storage.sh"
fi
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
