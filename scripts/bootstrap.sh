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
fi
val="$(prompt_value "LLM API Key (LiteLLM)" OPENAI_API_KEY "$current")"
[[ -n "$val" ]] && env_set OPENAI_API_KEY "$val"

# SAM.gov
current="$(env_get SAM_API_KEY)"
if [[ -z "$current" ]]; then
  echo ""
  echo "   SAM.gov API key enables government opportunities search."
  echo "   Get one at: https://sam.gov/content/entity-registration"
fi
val="$(prompt_value "SAM.gov API Key" SAM_API_KEY "$current")"
[[ -n "$val" ]] && env_set SAM_API_KEY "$val"

# Microsoft Graph
current_tenant="$(env_get MS_TENANT_ID)"
if [[ -z "$current_tenant" ]]; then
  echo ""
  echo "   Microsoft Graph credentials enable SharePoint integration."
  echo "   Leave blank to skip (can be added later)."
fi
val="$(prompt_value "MS Graph Tenant ID" MS_TENANT_ID "$current_tenant")"
[[ -n "$val" ]] && env_set MS_TENANT_ID "$val"

current_client="$(env_get MS_CLIENT_ID)"
val="$(prompt_value "MS Graph Client ID" MS_CLIENT_ID "$current_client")"
[[ -n "$val" ]] && env_set MS_CLIENT_ID "$val"

current_secret="$(env_get MS_CLIENT_SECRET)"
val="$(prompt_value "MS Graph Client Secret" MS_CLIENT_SECRET "$current_secret")"
[[ -n "$val" ]] && env_set MS_CLIENT_SECRET "$val"

current_sender="$(env_get MS_EMAIL_SENDER)"
if [[ -z "$current_sender" ]]; then
  echo "   Email sender address enables invitation emails via Microsoft Graph."
  echo "   (e.g., noreply@yourcompany.com — must be a valid mailbox or shared mailbox)"
fi
val="$(prompt_value "MS Graph Email Sender" MS_EMAIL_SENDER "$current_sender")"
[[ -n "$val" ]] && env_set MS_EMAIL_SENDER "$val"

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

  echo "7. Services starting..."
  echo "   Open http://localhost:3000 to create your admin account via the setup wizard."
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
fi
echo "  Getting Started:"
echo "    Open http://localhost:3000 to create your admin account."
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
