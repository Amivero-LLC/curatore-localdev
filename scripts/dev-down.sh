#!/usr/bin/env bash
# ============================================================================
# Curatore Local Dev — Stop All Services
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "Stopping all Curatore services..."
echo ""

for svc in curatore-mcp-service curatore-frontend curatore-playwright-service curatore-document-service curatore-backend; do
  dir="${ROOT}/${svc}"
  if [[ -f "${dir}/docker-compose.yml" ]]; then
    echo "  Stopping ${svc}..."
    if [[ "$svc" == "curatore-backend" ]]; then
      cd "${dir}" && docker compose --profile postgres down 2>/dev/null || docker compose down 2>/dev/null || true
    else
      cd "${dir}" && docker compose down 2>/dev/null || true
    fi
  fi
done

echo ""
echo "All services stopped."
echo ""
echo "Note: The curatore-network is left intact. Remove it with:"
echo "  docker network rm curatore-network"
