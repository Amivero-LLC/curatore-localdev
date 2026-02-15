#!/usr/bin/env bash
# ============================================================================
# Curatore Local Dev — Service Status
# ============================================================================
set -euo pipefail

echo "============================================"
echo "  Curatore Service Status"
echo "============================================"
echo ""

docker ps --filter "name=curatore-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No containers running"

echo ""
echo "Network:"
docker network inspect curatore-network --format '{{range .Containers}}  {{.Name}}{{"\n"}}{{end}}' 2>/dev/null || echo "  curatore-network not found"
