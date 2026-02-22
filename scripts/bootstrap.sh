#!/usr/bin/env bash
# ============================================================================
# Curatore — Bootstrap Local Development Environment
# ============================================================================
# One-command setup from fresh clone to running platform.
#
# Usage:
#   ./scripts/bootstrap.sh              # Full interactive setup
#   ./scripts/bootstrap.sh --skip-start # Configure only, don't start services
#
# What it does:
#   1. Init/update git submodules
#   2. Create/update root .env (prompt for required values)
#   3. Generate random secrets for auto-generated fields
#   4. Distribute configs to per-service .env files + config.yml
#   5. Start all services via dev-up.sh
#   6. Seed admin user
#   7. Print summary with URLs and credentials
#
# Idempotency:
#   - Safe to re-run. Existing root .env values are preserved.
#   - Per-service .env files are always regenerated from root .env.
#   - Docker volumes (data) survive re-bootstrap.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ROOT}/.env"
ENV_EXAMPLE="${ROOT}/.env.example"

# Parse flags
SKIP_START=false
for arg in "$@"; do
  case "$arg" in
    --skip-start) SKIP_START=true ;;
  esac
done

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

# Generate a random hex string (for API keys)
gen_hex() { openssl rand -hex 32; }

# Generate a random base64 string (for passwords)
gen_b64() { openssl rand -base64 32 | tr -d '/+=' | head -c 32; }

# Read a value from the .env file
env_get() {
  local key="$1"
  local default="${2:-}"
  local value
  value="$(grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')" || true
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

# Write or update a key in the .env file
env_set() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    # Update existing line (macOS-compatible sed)
    sed -i '' "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}" 2>/dev/null ||
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    echo "${key}=${value}" >> "${ENV_FILE}"
  fi
}

# Prompt for a value, showing current/default
prompt_value() {
  local label="$1"
  local key="$2"
  local current="$3"
  local input

  if [[ -n "$current" && "$current" != "your-api-key-here" ]]; then
    read -rp "  ${label} [${current:0:8}...]: " input
    echo "${input:-$current}"
  else
    read -rp "  ${label}: " input
    echo "$input"
  fi
}

echo "============================================"
echo "  Curatore Bootstrap"
echo "============================================"
echo ""

# --------------------------------------------------------------------------
# 1. Init/update git submodules
# --------------------------------------------------------------------------
echo "1. Initializing git submodules..."
cd "$ROOT"
git submodule update --init --recursive
echo "   Submodules ready."
echo ""

# --------------------------------------------------------------------------
# 2. Create/load root .env
# --------------------------------------------------------------------------
echo "2. Configuring environment..."

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "   Created .env from .env.example"
  else
    touch "$ENV_FILE"
    echo "   Created empty .env"
  fi
else
  echo "   Using existing .env"
fi
echo ""

# --------------------------------------------------------------------------
# 3. Prompt for required values (only if empty)
# --------------------------------------------------------------------------
echo "3. Checking required credentials..."
echo "   (Press Enter to keep existing values)"
echo ""

# LLM
current="$(env_get OPENAI_API_KEY)"
if [[ -z "$current" || "$current" == "your-api-key-here" ]]; then
  echo "   LLM API key is required for document analysis and CWR."
  val="$(prompt_value "LLM API Key (LiteLLM)" OPENAI_API_KEY "$current")"
  [[ -n "$val" ]] && env_set OPENAI_API_KEY "$val"
else
  echo "   LLM API Key: ${current:0:8}... (already set)"
fi

# SAM.gov
current="$(env_get SAM_API_KEY)"
if [[ -z "$current" ]]; then
  echo ""
  echo "   SAM.gov API key enables government opportunities search."
  echo "   Get one at: https://sam.gov/content/entity-registration"
  val="$(prompt_value "SAM.gov API Key" SAM_API_KEY "$current")"
  [[ -n "$val" ]] && env_set SAM_API_KEY "$val"
else
  echo "   SAM.gov API Key: ${current:0:8}... (already set)"
fi

# Microsoft Graph
current_tenant="$(env_get MS_TENANT_ID)"
if [[ -z "$current_tenant" ]]; then
  echo ""
  echo "   Microsoft Graph credentials enable SharePoint integration."
  echo "   Leave blank to skip (can be added later)."
  val="$(prompt_value "MS Graph Tenant ID" MS_TENANT_ID "$current_tenant")"
  [[ -n "$val" ]] && env_set MS_TENANT_ID "$val"
else
  echo "   MS Graph Tenant ID: ${current_tenant:0:8}... (already set)"
fi

current_client="$(env_get MS_CLIENT_ID)"
if [[ -z "$current_client" ]]; then
  val="$(prompt_value "MS Graph Client ID" MS_CLIENT_ID "$current_client")"
  [[ -n "$val" ]] && env_set MS_CLIENT_ID "$val"
else
  echo "   MS Graph Client ID: ${current_client:0:8}... (already set)"
fi

current_secret="$(env_get MS_CLIENT_SECRET)"
if [[ -z "$current_secret" ]]; then
  val="$(prompt_value "MS Graph Client Secret" MS_CLIENT_SECRET "$current_secret")"
  [[ -n "$val" ]] && env_set MS_CLIENT_SECRET "$val"
else
  echo "   MS Graph Client Secret: ${current_secret:0:8}... (already set)"
fi

current_sender="$(env_get MS_EMAIL_SENDER)"
if [[ -z "$current_sender" ]]; then
  echo "   Email sender address enables invitation emails via Microsoft Graph."
  echo "   (e.g., noreply@yourcompany.com — must be a valid mailbox or shared mailbox)"
  val="$(prompt_value "MS Graph Email Sender" MS_EMAIL_SENDER "$current_sender")"
  [[ -n "$val" ]] && env_set MS_EMAIL_SENDER "$val"
else
  echo "   MS Graph Email Sender: ${current_sender:0:8}... (already set)"
fi

# Embedding model selection
current_embed="$(env_get LLM_EMBEDDING_MODEL)"
if [[ -z "$current_embed" ]]; then
  echo ""
  echo "   Embedding model for semantic search:"
  echo "     1) text-embedding-3-large   (OpenAI, 3072 dims, default)"
  echo "     2) text-embedding-3-small   (OpenAI, 1536 dims)"
  echo "     3) amazon-titan-embed-text-v2:0  (AWS Bedrock, 1024 dims)"
  read -rp "  Embedding model [1/2/3] (default: 1): " embed_choice
  case "${embed_choice:-1}" in
    2) env_set LLM_EMBEDDING_MODEL "text-embedding-3-small" ;;
    3) env_set LLM_EMBEDDING_MODEL "amazon-titan-embed-text-v2:0" ;;
    *) env_set LLM_EMBEDDING_MODEL "text-embedding-3-large" ;;
  esac
else
  echo "   Embedding model: ${current_embed} (already set)"
fi

echo ""

# --------------------------------------------------------------------------
# 4. Generate random secrets for blank auto-generated fields
# --------------------------------------------------------------------------
echo "4. Generating secrets for empty fields..."

changed=0
for key_gen in \
  "JWT_SECRET_KEY:hex" \
  "MCP_API_KEY:hex" \
  "DOCUMENT_SERVICE_API_KEY:hex" \
  "PLAYWRIGHT_API_KEY:hex" \
  "MINIO_ROOT_PASSWORD:b64" \
  "POSTGRES_PASSWORD:b64"; do

  key="${key_gen%%:*}"
  gen_type="${key_gen##*:}"
  current="$(env_get "$key")"

  if [[ -z "$current" ]]; then
    if [[ "$gen_type" == "hex" ]]; then
      new_val="$(gen_hex)"
    else
      new_val="$(gen_b64)"
    fi
    env_set "$key" "$new_val"
    echo "   Generated ${key}"
    changed=$((changed + 1))
  fi
done

# Ensure MINIO_ROOT_USER has a value
if [[ -z "$(env_get MINIO_ROOT_USER)" ]]; then
  env_set MINIO_ROOT_USER "admin"
fi

if [[ $changed -eq 0 ]]; then
  echo "   All secrets already set."
fi
echo ""

# --------------------------------------------------------------------------
# 5. Distribute to per-service config files
# --------------------------------------------------------------------------
echo "5. Distributing configs to services..."
"${SCRIPT_DIR}/generate-env.sh"
echo ""

# --------------------------------------------------------------------------
# 6. Start services (unless --skip-start)
# --------------------------------------------------------------------------
if [[ "$SKIP_START" == "true" ]]; then
  echo "6. Skipping service startup (--skip-start)"
  echo ""
else
  echo "6. Starting all services..."
  echo ""
  "${SCRIPT_DIR}/dev-up.sh" --with-postgres
  echo ""

  # dev-up.sh waits for backend health, so the seed command can run immediately.
  # Idempotent — skips if an admin already exists.
  echo "7. Seeding admin user from .env credentials..."
  docker exec curatore-backend python -m app.core.commands.seed --create-admin 2>&1 | tail -5
  echo ""
fi

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
echo "============================================"
echo "  Bootstrap Complete!"
echo "============================================"
echo ""
if [[ "$SKIP_START" == "false" ]]; then
  echo "  Services:"
  echo "    Frontend:         http://localhost:3000"
  echo "    Backend API:      http://localhost:8000"
  echo "    API Docs:         http://localhost:8000/docs"
  echo "    Document Service: http://localhost:8010"
  echo "    Playwright:       http://localhost:8011"
  echo "    MCP Gateway:      http://localhost:8020"
  echo "    MinIO Console:    http://localhost:9001"
  echo ""
  echo "  Admin Login (from .env — development only):"
  echo "    Email:    $(env_get ADMIN_EMAIL "admin@example.com")"
  echo "    Password: $(env_get ADMIN_PASSWORD "changeme")"
  echo ""
fi
echo "  Getting Started:"
echo "    Open http://localhost:3000 and log in with the admin credentials above."
echo ""
echo "  Config files:"
echo "    Root:     .env (edit this, then run ./scripts/generate-env.sh)"
echo "    Backend:  curatore-backend/.env + curatore-backend/config.yml"
echo ""
echo "  Useful commands:"
echo "    ./scripts/dev-up.sh --with-postgres    Start services"
echo "    ./scripts/dev-down.sh                  Stop services"
echo "    ./scripts/dev-logs.sh                  View logs"
echo "    ./scripts/generate-env.sh              Regenerate service configs"
echo "    ./scripts/generate-env.sh --check      Validate root .env"
echo "============================================"
