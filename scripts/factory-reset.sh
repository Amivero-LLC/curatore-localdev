#!/usr/bin/env bash
# ============================================================================
# Curatore Local Dev — Factory Reset
# ============================================================================
# Stops all services, removes all containers/images/volumes, cleans cached
# and temporary files, then re-runs bootstrap.sh for a fresh start.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SKIP_BOOTSTRAP=false
FORCE=false

for arg in "$@"; do
  case "$arg" in
    --skip-bootstrap) SKIP_BOOTSTRAP=true ;;
    --force|-f)       FORCE=true ;;
    --help|-h)
      echo "Usage: factory-reset.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --force, -f        Skip confirmation prompt"
      echo "  --skip-bootstrap   Stop at cleanup; don't re-run bootstrap.sh"
      echo "  --help, -h         Show this help"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      exit 1
      ;;
  esac
done

echo "============================================================================"
echo "  Curatore — Factory Reset"
echo "============================================================================"
echo ""
echo "This will:"
echo "  1. Stop all running Curatore services"
echo "  2. Remove all Curatore Docker containers, images, and volumes"
echo "  3. Remove the curatore-network Docker network"
echo "  4. Delete cached/temp files (node_modules, .next, __pycache__, .venv, etc.)"
if [[ "$SKIP_BOOTSTRAP" == false ]]; then
  echo "  5. Re-run bootstrap.sh for a fresh setup"
fi
echo ""

if [[ "$FORCE" == false ]]; then
  read -rp "Are you sure? This cannot be undone. [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
  echo ""
fi

# --------------------------------------------------------------------------
# Step 1: Stop all services
# --------------------------------------------------------------------------
echo "Step 1: Stopping all services..."
echo ""

for svc in curatore-mcp-service curatore-frontend curatore-playwright-service curatore-document-service curatore-backend; do
  dir="${ROOT}/${svc}"
  if [[ -f "${dir}/docker-compose.yml" ]]; then
    echo "  Stopping ${svc}..."
    if [[ "$svc" == "curatore-backend" ]]; then
      cd "${dir}" && docker compose --profile postgres down 2>/dev/null || docker compose down 2>/dev/null || true
    elif [[ "$svc" == "curatore-document-service" ]]; then
      cd "${dir}" && docker compose down 2>/dev/null || true
    else
      cd "${dir}" && docker compose down 2>/dev/null || true
    fi
  fi
done

echo "  All services stopped."
echo ""

# --------------------------------------------------------------------------
# Step 2: Remove Docker containers
# --------------------------------------------------------------------------
echo "Step 2: Removing Curatore Docker containers..."

containers=$(docker ps -a --filter "name=curatore-" --format "{{.ID}}" 2>/dev/null || true)
if [[ -n "$containers" ]]; then
  echo "$containers" | xargs docker rm -f 2>/dev/null || true
  echo "  Containers removed."
else
  echo "  No containers found."
fi
echo ""

# --------------------------------------------------------------------------
# Step 3: Remove Docker images
# --------------------------------------------------------------------------
echo "Step 3: Removing Curatore Docker images..."

images=$(docker images --format "{{.Repository}} {{.ID}}" 2>/dev/null | grep curatore | awk '{print $2}' || true)
if [[ -n "$images" ]]; then
  echo "$images" | xargs docker rmi -f 2>/dev/null || true
  echo "  Images removed."
else
  echo "  No images found."
fi
echo ""

# --------------------------------------------------------------------------
# Step 4: Remove Docker volumes
# --------------------------------------------------------------------------
echo "Step 4: Removing Curatore Docker volumes..."

volumes=$(docker volume ls --format "{{.Name}}" 2>/dev/null | grep curatore || true)
if [[ -n "$volumes" ]]; then
  echo "$volumes" | xargs docker volume rm -f 2>/dev/null || true
  echo "  Volumes removed."
else
  echo "  No volumes found."
fi
echo ""

# --------------------------------------------------------------------------
# Step 5: Remove Docker network
# --------------------------------------------------------------------------
echo "Step 5: Removing curatore-network..."

docker network rm curatore-network 2>/dev/null || true
echo "  Done."
echo ""

# --------------------------------------------------------------------------
# Step 6: Clean cached and temporary files
# --------------------------------------------------------------------------
echo "Step 6: Cleaning cached and temporary files..."

SERVICES=(
  curatore-backend
  curatore-frontend
  curatore-document-service
  curatore-playwright-service
  curatore-mcp-service
)

for svc in "${SERVICES[@]}"; do
  dir="${ROOT}/${svc}"
  [[ -d "$dir" ]] || continue

  cleaned=()

  # Node.js / Next.js
  if [[ -d "${dir}/node_modules" ]]; then
    rm -rf "${dir}/node_modules"
    cleaned+=("node_modules")
  fi
  if [[ -d "${dir}/.next" ]]; then
    rm -rf "${dir}/.next"
    cleaned+=(".next")
  fi

  # Python virtual environments
  if [[ -d "${dir}/.venv" ]]; then
    rm -rf "${dir}/.venv"
    cleaned+=(".venv")
  fi
  if [[ -d "${dir}/venv" ]]; then
    rm -rf "${dir}/venv"
    cleaned+=("venv")
  fi

  # Python caches
  pycache_count=$(find "${dir}" -type d -name "__pycache__" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$pycache_count" -gt 0 ]]; then
    find "${dir}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    cleaned+=("__pycache__ (${pycache_count})")
  fi
  pyc_count=$(find "${dir}" -type f -name "*.pyc" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$pyc_count" -gt 0 ]]; then
    find "${dir}" -type f -name "*.pyc" -delete 2>/dev/null || true
    cleaned+=(".pyc (${pyc_count})")
  fi

  # Test / lint caches
  for cache_dir in .pytest_cache .mypy_cache .ruff_cache; do
    if [[ -d "${dir}/${cache_dir}" ]]; then
      rm -rf "${dir}/${cache_dir}"
      cleaned+=("${cache_dir}")
    fi
  done

  # Build artifacts
  for build_dir in dist build .eggs *.egg-info; do
    # Use find for glob pattern (egg-info)
    found=$(find "${dir}" -maxdepth 1 -name "$build_dir" -type d 2>/dev/null || true)
    if [[ -n "$found" ]]; then
      rm -rf $found
      cleaned+=("${build_dir}")
    fi
  done

  if [[ ${#cleaned[@]} -gt 0 ]]; then
    echo "  ${svc}: ${cleaned[*]}"
  else
    echo "  ${svc}: (clean)"
  fi
done

echo ""
echo "  Cleanup complete."
echo ""

# --------------------------------------------------------------------------
# Step 7: Re-run bootstrap
# --------------------------------------------------------------------------
if [[ "$SKIP_BOOTSTRAP" == true ]]; then
  echo "============================================================================"
  echo "  Factory reset complete (bootstrap skipped)."
  echo "  Run ./scripts/bootstrap.sh when ready."
  echo "============================================================================"
else
  echo "============================================================================"
  echo "  Cleanup complete — starting bootstrap..."
  echo "============================================================================"
  echo ""
  exec "${SCRIPT_DIR}/bootstrap.sh"
fi
