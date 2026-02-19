#!/usr/bin/env bash
# ============================================================================
# Curatore — Generate Per-Service Config Files
# ============================================================================
# Reads the root .env and distributes settings to each service's .env and
# config.yml. Run this after editing the root .env to propagate changes.
#
# Usage:
#   ./scripts/generate-env.sh          # Generate all service configs
#   ./scripts/generate-env.sh --check  # Validate root .env has required fields
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ROOT}/.env"
TEMPLATE_DIR="${SCRIPT_DIR}/templates"

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

# Safe .env parser — reads KEY=VALUE pairs, ignores comments and blank lines.
# Does NOT export into current shell to avoid side effects.
env_get() {
  local key="$1"
  local default="${2:-}"
  local value
  value="$(grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')" || true
  # Strip surrounding quotes if present
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  if [[ -z "$value" ]]; then
    echo "$default"
  else
    echo "$value"
  fi
}

warn() { echo "  WARNING: $*" >&2; }
info() { echo "  $*"; }

# --------------------------------------------------------------------------
# Validate root .env exists
# --------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Root .env not found at ${ENV_FILE}"
  echo "Run ./scripts/bootstrap.sh to create it, or copy .env.example:"
  echo "  cp .env.example .env"
  exit 1
fi

# --------------------------------------------------------------------------
# --check mode: validate required fields
# --------------------------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
  echo "Validating root .env..."
  errors=0

  for key in OPENAI_API_KEY MS_TENANT_ID MS_CLIENT_ID MS_CLIENT_SECRET SAM_API_KEY; do
    val="$(env_get "$key")"
    if [[ -z "$val" || "$val" == "your-api-key-here" ]]; then
      warn "$key is empty or placeholder"
      errors=$((errors + 1))
    fi
  done

  for key in JWT_SECRET_KEY MCP_API_KEY DOCUMENT_SERVICE_API_KEY PLAYWRIGHT_API_KEY MINIO_ROOT_PASSWORD POSTGRES_PASSWORD; do
    val="$(env_get "$key")"
    if [[ -z "$val" ]]; then
      warn "$key is empty (should be auto-generated)"
      errors=$((errors + 1))
    fi
  done

  if [[ $errors -gt 0 ]]; then
    echo ""
    echo "Found $errors issue(s). Run ./scripts/bootstrap.sh to fix."
    exit 1
  else
    echo "All required fields present."
    exit 0
  fi
fi

# --------------------------------------------------------------------------
# Read all values from root .env
# --------------------------------------------------------------------------
echo "Reading root .env..."

OPENAI_API_KEY="$(env_get OPENAI_API_KEY)"
OPENAI_BASE_URL="$(env_get OPENAI_BASE_URL "https://litellm.prod.amivero-solutions.com")"
OPENAI_MODEL="$(env_get OPENAI_MODEL "claude-4-5-sonnet")"
LLM_EMBEDDING_MODEL="$(env_get LLM_EMBEDDING_MODEL "text-embedding-3-large")"
case "$LLM_EMBEDDING_MODEL" in
  text-embedding-3-large)          LLM_EMBEDDING_DIMENSIONS=3072 ;;
  text-embedding-3-small)          LLM_EMBEDDING_DIMENSIONS=1536 ;;
  amazon-titan-embed-text-v2:0)    LLM_EMBEDDING_DIMENSIONS=1024 ;;
  text-embedding-ada-002)          LLM_EMBEDDING_DIMENSIONS=1536 ;;
  *)                               LLM_EMBEDDING_DIMENSIONS=1536 ;;
esac
LLM_QUICK_MODEL="$(env_get LLM_QUICK_MODEL "$OPENAI_MODEL")"
LLM_QUICK_TEMPERATURE="$(env_get LLM_QUICK_TEMPERATURE "0.1")"
LLM_STANDARD_MODEL="$(env_get LLM_STANDARD_MODEL "$OPENAI_MODEL")"
LLM_STANDARD_TEMPERATURE="$(env_get LLM_STANDARD_TEMPERATURE "0.5")"
LLM_QUALITY_MODEL="$(env_get LLM_QUALITY_MODEL "$OPENAI_MODEL")"
LLM_QUALITY_TEMPERATURE="$(env_get LLM_QUALITY_TEMPERATURE "0.3")"
LLM_BULK_MODEL="$(env_get LLM_BULK_MODEL "$OPENAI_MODEL")"
LLM_BULK_TEMPERATURE="$(env_get LLM_BULK_TEMPERATURE "0.3")"
LLM_REASONING_MODEL="$(env_get LLM_REASONING_MODEL "$OPENAI_MODEL")"
LLM_REASONING_TEMPERATURE="$(env_get LLM_REASONING_TEMPERATURE "0.2")"
MS_TENANT_ID="$(env_get MS_TENANT_ID)"
MS_CLIENT_ID="$(env_get MS_CLIENT_ID)"
MS_CLIENT_SECRET="$(env_get MS_CLIENT_SECRET)"
SAM_API_KEY="$(env_get SAM_API_KEY)"
JWT_SECRET_KEY="$(env_get JWT_SECRET_KEY)"
MCP_API_KEY="$(env_get MCP_API_KEY)"
DOCUMENT_SERVICE_API_KEY="$(env_get DOCUMENT_SERVICE_API_KEY)"
PLAYWRIGHT_API_KEY="$(env_get PLAYWRIGHT_API_KEY)"
MINIO_ROOT_USER="$(env_get MINIO_ROOT_USER "admin")"
MINIO_ROOT_PASSWORD="$(env_get MINIO_ROOT_PASSWORD)"
POSTGRES_DB="$(env_get POSTGRES_DB "curatore")"
POSTGRES_USER="$(env_get POSTGRES_USER "curatore")"
POSTGRES_PASSWORD="$(env_get POSTGRES_PASSWORD)"
ADMIN_EMAIL="$(env_get ADMIN_EMAIL "admin@example.com")"
ADMIN_PASSWORD="$(env_get ADMIN_PASSWORD "changeme")"
ADMIN_USERNAME="$(env_get ADMIN_USERNAME "admin")"
ADMIN_FULL_NAME="$(env_get ADMIN_FULL_NAME "Admin User")"
DEFAULT_ORG_NAME="$(env_get DEFAULT_ORG_NAME "Default Organization")"
DEFAULT_ORG_SLUG="$(env_get DEFAULT_ORG_SLUG "default")"
DEBUG="$(env_get DEBUG "true")"
ENABLE_POSTGRES_SERVICE="$(env_get ENABLE_POSTGRES_SERVICE "true")"
CORS_ORIGINS="$(env_get CORS_ORIGINS '["http://localhost:3000"]')"
ENABLE_AUTH="$(env_get ENABLE_AUTH "true")"
EMAIL_BACKEND="$(env_get EMAIL_BACKEND "console")"
EMAIL_FROM_ADDRESS="$(env_get EMAIL_FROM_ADDRESS "noreply@curatore.app")"
EMAIL_FROM_NAME="$(env_get EMAIL_FROM_NAME "Curatore")"
MS_EMAIL_SENDER="$(env_get MS_EMAIL_SENDER)"
SEARCH_ENABLED="$(env_get SEARCH_ENABLED "true")"
LOG_LEVEL="$(env_get LOG_LEVEL "INFO")"
CELERY_CONCURRENCY_DOCUMENTS="$(env_get CELERY_CONCURRENCY_DOCUMENTS "4")"
CELERY_CONCURRENCY_GENERAL="$(env_get CELERY_CONCURRENCY_GENERAL "2")"

# Derived values
DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"

# --------------------------------------------------------------------------
# 1. Generate curatore-backend/.env
# --------------------------------------------------------------------------
info "Writing curatore-backend/.env"
cat > "${ROOT}/curatore-backend/.env" << BACKEND_ENV
# Generated by generate-env.sh — do not edit directly.
# Edit the root .env and re-run: ./scripts/generate-env.sh

# Debug / Development
DEBUG=${DEBUG}
CORS_ORIGINS=${CORS_ORIGINS}
ENABLE_AUTH=${ENABLE_AUTH}
ENABLE_POSTGRES_SERVICE=${ENABLE_POSTGRES_SERVICE}

# LLM
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENAI_BASE_URL=${OPENAI_BASE_URL}
OPENAI_MODEL=${OPENAI_MODEL}

# Database
DATABASE_URL=${DATABASE_URL}
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# Auth
JWT_SECRET_KEY=${JWT_SECRET_KEY}

# Service API Keys
DOCUMENT_SERVICE_API_KEY=${DOCUMENT_SERVICE_API_KEY}
PLAYWRIGHT_API_KEY=${PLAYWRIGHT_API_KEY}
MCP_API_KEY=${MCP_API_KEY}

# Microsoft Graph (SharePoint)
MS_TENANT_ID=${MS_TENANT_ID}
MS_CLIENT_ID=${MS_CLIENT_ID}
MS_CLIENT_SECRET=${MS_CLIENT_SECRET}

# SAM.gov
SAM_API_KEY=${SAM_API_KEY}

# Celery (Docker container names — must match redis service)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CELERY_CONCURRENCY_DOCUMENTS=${CELERY_CONCURRENCY_DOCUMENTS}
CELERY_CONCURRENCY_GENERAL=${CELERY_CONCURRENCY_GENERAL}

# Service Auth (delegated auth from MCP service)
TRUSTED_SERVICE_KEY=${MCP_API_KEY}

# MinIO (Docker container names — must match minio service)
MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=${MINIO_ROOT_USER}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
MINIO_ACCESS_KEY=${MINIO_ROOT_USER}
MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD}

# Email
EMAIL_BACKEND=${EMAIL_BACKEND}
EMAIL_FROM_ADDRESS=${EMAIL_FROM_ADDRESS}
EMAIL_FROM_NAME=${EMAIL_FROM_NAME}
FRONTEND_BASE_URL=http://localhost:3000

# Seeding
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
ADMIN_FULL_NAME=${ADMIN_FULL_NAME}
DEFAULT_ORG_NAME=${DEFAULT_ORG_NAME}
DEFAULT_ORG_SLUG=${DEFAULT_ORG_SLUG}

# Search
SEARCH_ENABLED=${SEARCH_ENABLED}
BACKEND_ENV

# --------------------------------------------------------------------------
# 2. Generate curatore-backend/config.yml from template
# --------------------------------------------------------------------------
info "Writing curatore-backend/config.yml"

TEMPLATE="${TEMPLATE_DIR}/config.yml.template"
if [[ ! -f "$TEMPLATE" ]]; then
  echo "ERROR: Template not found at ${TEMPLATE}"
  exit 1
fi

# Determine MS Graph enabled state
if [[ -n "$MS_TENANT_ID" && -n "$MS_CLIENT_ID" && -n "$MS_CLIENT_SECRET" ]]; then
  MS_GRAPH_ENABLED="true"
else
  MS_GRAPH_ENABLED="false"
fi

# Enable MS Graph email when Graph is configured and a sender address is set
if [[ "$MS_GRAPH_ENABLED" == "true" && -n "$MS_EMAIL_SENDER" ]]; then
  MS_ENABLE_EMAIL="true"
else
  MS_ENABLE_EMAIL="false"
fi

# Use sed to substitute all placeholders.
# We use | as delimiter to avoid conflicts with URLs containing /
sed \
  -e "s|__OPENAI_API_KEY__|${OPENAI_API_KEY}|g" \
  -e "s|__OPENAI_BASE_URL__|${OPENAI_BASE_URL}|g" \
  -e "s|__OPENAI_MODEL__|${OPENAI_MODEL}|g" \
  -e "s|__LLM_EMBEDDING_MODEL__|${LLM_EMBEDDING_MODEL}|g" \
  -e "s|__LLM_EMBEDDING_DIMENSIONS__|${LLM_EMBEDDING_DIMENSIONS}|g" \
  -e "s|__LLM_QUICK_MODEL__|${LLM_QUICK_MODEL}|g" \
  -e "s|__LLM_QUICK_TEMPERATURE__|${LLM_QUICK_TEMPERATURE}|g" \
  -e "s|__LLM_STANDARD_MODEL__|${LLM_STANDARD_MODEL}|g" \
  -e "s|__LLM_STANDARD_TEMPERATURE__|${LLM_STANDARD_TEMPERATURE}|g" \
  -e "s|__LLM_QUALITY_MODEL__|${LLM_QUALITY_MODEL}|g" \
  -e "s|__LLM_QUALITY_TEMPERATURE__|${LLM_QUALITY_TEMPERATURE}|g" \
  -e "s|__LLM_BULK_MODEL__|${LLM_BULK_MODEL}|g" \
  -e "s|__LLM_BULK_TEMPERATURE__|${LLM_BULK_TEMPERATURE}|g" \
  -e "s|__LLM_REASONING_MODEL__|${LLM_REASONING_MODEL}|g" \
  -e "s|__LLM_REASONING_TEMPERATURE__|${LLM_REASONING_TEMPERATURE}|g" \
  -e "s|__DOCUMENT_SERVICE_API_KEY__|${DOCUMENT_SERVICE_API_KEY}|g" \
  -e "s|__PLAYWRIGHT_API_KEY__|${PLAYWRIGHT_API_KEY}|g" \
  -e "s|__MINIO_ACCESS_KEY__|${MINIO_ROOT_USER}|g" \
  -e "s|__MINIO_SECRET_KEY__|${MINIO_ROOT_PASSWORD}|g" \
  -e "s|__MS_GRAPH_ENABLED__|${MS_GRAPH_ENABLED}|g" \
  -e "s|__MS_TENANT_ID__|${MS_TENANT_ID}|g" \
  -e "s|__MS_CLIENT_ID__|${MS_CLIENT_ID}|g" \
  -e "s|__MS_CLIENT_SECRET__|${MS_CLIENT_SECRET}|g" \
  -e "s|__MS_ENABLE_EMAIL__|${MS_ENABLE_EMAIL}|g" \
  -e "s|__MS_EMAIL_SENDER__|${MS_EMAIL_SENDER}|g" \
  "${TEMPLATE}" > "${ROOT}/curatore-backend/config.yml"

# --------------------------------------------------------------------------
# 3. Generate curatore-document-service/.env
# --------------------------------------------------------------------------
info "Writing curatore-document-service/.env"
cat > "${ROOT}/curatore-document-service/.env" << DOC_ENV
# Generated by generate-env.sh — do not edit directly.
SERVICE_API_KEY=${DOCUMENT_SERVICE_API_KEY}
REDIS_URL=redis://redis:6379/2
LOG_LEVEL=${LOG_LEVEL}
DEBUG=${DEBUG}
DOC_ENV

# --------------------------------------------------------------------------
# 4. Generate curatore-playwright-service/.env
# --------------------------------------------------------------------------
info "Writing curatore-playwright-service/.env"
cat > "${ROOT}/curatore-playwright-service/.env" << PW_ENV
# Generated by generate-env.sh — do not edit directly.
SERVICE_API_KEY=${PLAYWRIGHT_API_KEY}
REDIS_URL=redis://redis:6379/2
LOG_LEVEL=${LOG_LEVEL}
DEBUG=${DEBUG}
PW_ENV

# --------------------------------------------------------------------------
# 5. Generate curatore-mcp-service/.env
# --------------------------------------------------------------------------
info "Writing curatore-mcp-service/.env"
cat > "${ROOT}/curatore-mcp-service/.env" << MCP_ENV
# Generated by generate-env.sh — do not edit directly.
BACKEND_URL=http://backend:8000
BACKEND_TIMEOUT=30
SERVICE_API_KEY=${MCP_API_KEY}
BACKEND_API_KEY=${MCP_API_KEY}
REDIS_URL=redis://redis:6379/2
LOG_LEVEL=${LOG_LEVEL}
DEBUG=${DEBUG}
MCP_ENV

# --------------------------------------------------------------------------
# 6. Generate curatore-frontend/.env
# --------------------------------------------------------------------------
info "Writing curatore-frontend/.env"
cat > "${ROOT}/curatore-frontend/.env" << FRONTEND_ENV
# Generated by generate-env.sh — do not edit directly.
# Edit the root .env and re-run: ./scripts/generate-env.sh

# Backend API URL (browser-accessible)
NEXT_PUBLIC_API_URL=http://localhost:8000
FRONTEND_ENV

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
echo ""
echo "Config files generated:"
echo "  curatore-backend/.env"
echo "  curatore-backend/config.yml"
echo "  curatore-document-service/.env"
echo "  curatore-playwright-service/.env"
echo "  curatore-mcp-service/.env"
echo "  curatore-frontend/.env"
echo ""
echo "To start services: ./scripts/dev-up.sh --with-postgres"
