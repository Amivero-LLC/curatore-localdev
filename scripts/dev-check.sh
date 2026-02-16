#!/usr/bin/env bash
# ==============================================================================
# Curatore Local Dev — Unified Quality Check
# ------------------------------------------------------------------------------
# Runs linting, security scanning, and tests across all Curatore services
# using Docker containers (ephemeral via docker compose run).
#
# Usage:
#   ./scripts/dev-check.sh                    # Run everything
#   ./scripts/dev-check.sh --lint-only        # Just linting
#   ./scripts/dev-check.sh --security-only    # Just security scans
#   ./scripts/dev-check.sh --test-only        # Just tests
#   ./scripts/dev-check.sh --service=backend  # Single service only
#
# Env overrides:
#   SKIP_LINT=1        Skip linting
#   SKIP_SECURITY=1    Skip security scanning
#   SKIP_TESTS=1       Skip test execution
#
# Services: backend, document-service, playwright, mcp, frontend
# ==============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_DIR="${REPORT_DIR:-$ROOT/logs/quality_reports/$TIMESTAMP}"
mkdir -p "$REPORT_DIR"

SUMMARY_FILE="$REPORT_DIR/summary.log"
touch "$SUMMARY_FILE"

# Skip flags
SKIP_LINT=${SKIP_LINT:-0}
SKIP_SECURITY=${SKIP_SECURITY:-0}
SKIP_TESTS=${SKIP_TESTS:-0}

# Parse CLI args
MODE="all"
SERVICE_FILTER=""
for arg in "$@"; do
  case "$arg" in
    --lint-only)     MODE="lint" ;;
    --security-only) MODE="security" ;;
    --test-only)     MODE="test" ;;
    --service=*)     SERVICE_FILTER="${arg#--service=}" ;;
    --help|-h)
      echo "Usage: $0 [--lint-only|--security-only|--test-only] [--service=NAME]"
      echo "  Services: backend, document-service, playwright, mcp, frontend"
      echo "  Env: SKIP_LINT=1, SKIP_SECURITY=1, SKIP_TESTS=1"
      exit 0 ;;
  esac
done

# -------- Service directory map --------
# Compose dir, compose service name, test path relative to compose dir, requirements-dev path
BACKEND_DIR="${ROOT}/curatore-backend"
DOCSVC_DIR="${ROOT}/curatore-document-service"
PLAYWRIGHT_DIR="${ROOT}/curatore-playwright-service"
MCP_DIR="${ROOT}/curatore-mcp-service"
FRONTEND_DIR="${ROOT}/curatore-frontend"

# -------- Utilities --------

log_note() {
  echo "$*" | tee -a "$SUMMARY_FILE"
}

print_header() {
  local title="$1"
  echo "" | tee -a "$SUMMARY_FILE"
  echo "============================================" | tee -a "$SUMMARY_FILE"
  echo "  $title" | tee -a "$SUMMARY_FILE"
  echo "============================================" | tee -a "$SUMMARY_FILE"
}

RESULTS=()

record_result() {
  local category="$1"; shift
  local service="$1"; shift
  local tool="$1"; shift
  local status="$1"; shift
  local note="${1:-}"
  RESULTS+=("${category}|${service}|${tool}|${status}|${note}")
}

should_run_service() {
  local svc="$1"
  [[ -z "$SERVICE_FILTER" || "$SERVICE_FILTER" == "$svc" ]]
}

# -------- Pre-flight --------

preflight() {
  print_header "Pre-flight Checks"

  # Verify Docker is running
  if ! docker info &>/dev/null; then
    log_note "❌ Docker is not running. Start Docker and try again."
    exit 2
  fi
  log_note "✅ Docker is running"

  # Verify minimum services are up
  local running
  running=$(docker ps --filter "name=curatore-" --format "{{.Names}}" 2>/dev/null)
  if ! echo "$running" | grep -q "curatore-backend"; then
    log_note "❌ curatore-backend is not running. Start services with ./scripts/dev-up.sh"
    exit 2
  fi
  if ! echo "$running" | grep -q "curatore-redis"; then
    log_note "❌ curatore-redis is not running. Start services with ./scripts/dev-up.sh"
    exit 2
  fi
  log_note "✅ Required services running (backend, redis)"
  log_note "   Running: $(echo "$running" | tr '\n' ' ')"
  log_note "📁 Reports: $REPORT_DIR"
}

# -------- Phase 2: Linting --------

run_lint_python_service() {
  local svc="$1"; shift
  local compose_dir="$1"; shift
  local compose_svc="$1"; shift
  local log="$REPORT_DIR/lint_${svc}.log"

  if [[ ! -d "$compose_dir" ]]; then
    log_note "  [SKIP] $svc (ruff) — directory not found"
    return 0
  fi

  log_note "  🔎 $svc (ruff) ..."
  local code=0
  (cd "$compose_dir" && docker compose run --rm --no-deps --user root --entrypoint="" "$compose_svc" \
    sh -c "pip install -q ruff >/dev/null 2>&1 && python -m ruff check /app/app --output-format=concise --line-length 120 --select E,F,W,I --ignore E501" \
  ) >"$log" 2>&1 || code=$?

  if [[ $code -eq 0 ]]; then
    log_note "  [PASS] $svc (ruff)"
    record_result "LINT" "$svc" "ruff" "PASS"
  else
    local issue_count
    issue_count=$(grep -cE "^.+:[0-9]+:[0-9]+:" "$log" 2>/dev/null || echo "?")
    log_note "  [FAIL] $svc (ruff) — $issue_count issues (see lint_${svc}.log)"
    record_result "LINT" "$svc" "ruff" "FAIL" "$issue_count issues"
  fi
}

run_lint_frontend() {
  local log="$REPORT_DIR/lint_frontend.log"

  if ! docker ps --format "{{.Names}}" | grep -q "curatore-frontend"; then
    log_note "  [SKIP] frontend (eslint) — container not running"
    return 0
  fi

  log_note "  🔎 frontend (eslint) ..."
  local code=0
  docker exec curatore-frontend npm run lint >"$log" 2>&1 || code=$?

  if [[ $code -eq 0 ]]; then
    log_note "  [PASS] frontend (eslint)"
    record_result "LINT" "frontend" "eslint" "PASS"
  else
    log_note "  [FAIL] frontend (eslint) — see lint_frontend.log"
    record_result "LINT" "frontend" "eslint" "FAIL"
  fi
}

run_lint_phase() {
  print_header "Phase: Linting"

  if [[ "$SKIP_LINT" == "1" ]]; then
    log_note "  [SKIP] Linting (SKIP_LINT=1)"
    return 0
  fi

  should_run_service "backend"          && run_lint_python_service "backend"          "$BACKEND_DIR"    "backend"
  should_run_service "document-service" && run_lint_python_service "document-service" "$DOCSVC_DIR"     "document-service"
  should_run_service "playwright"       && run_lint_python_service "playwright"       "$PLAYWRIGHT_DIR" "playwright"
  should_run_service "mcp"              && run_lint_python_service "mcp"              "$MCP_DIR"        "mcp"
  should_run_service "frontend"         && run_lint_frontend

  return 0
}

# -------- Phase 3: Security Scanning --------

run_security_bandit() {
  local svc="$1"; shift
  local compose_dir="$1"; shift
  local compose_svc="$1"; shift
  local log="$REPORT_DIR/bandit_${svc}.log"

  if [[ ! -d "$compose_dir" ]]; then
    return 0
  fi

  log_note "  🔎 $svc (bandit) ..."
  local code=0
  (cd "$compose_dir" && docker compose run --rm --no-deps --user root --entrypoint="" "$compose_svc" \
    sh -c "pip install -q bandit >/dev/null 2>&1 && bandit -r /app/app -ll" \
  ) >"$log" 2>&1 || code=$?

  if [[ $code -eq 0 ]]; then
    log_note "  [PASS] $svc (bandit)"
    record_result "SECURITY" "$svc" "bandit" "PASS"
  else
    local issue_count
    issue_count=$(grep -c ">> Issue:" "$log" 2>/dev/null || echo "0")
    if [[ "$issue_count" -gt 0 ]]; then
      log_note "  [WARN] $svc (bandit) — $issue_count findings (see bandit_${svc}.log)"
      record_result "SECURITY" "$svc" "bandit" "WARN" "$issue_count findings"
    else
      log_note "  [FAIL] $svc (bandit) — see bandit_${svc}.log"
      record_result "SECURITY" "$svc" "bandit" "FAIL"
    fi
  fi
}

run_security_pip_audit() {
  local svc="$1"; shift
  local compose_dir="$1"; shift
  local compose_svc="$1"; shift
  local log="$REPORT_DIR/pip_audit_${svc}.log"

  if [[ ! -d "$compose_dir" ]]; then
    return 0
  fi

  log_note "  🔎 $svc (pip-audit) ..."
  local code=0
  (cd "$compose_dir" && docker compose run --rm --no-deps --user root --entrypoint="" "$compose_svc" \
    sh -c "pip install -q pip-audit >/dev/null 2>&1 && pip-audit" \
  ) >"$log" 2>&1 || code=$?

  if [[ $code -eq 0 ]]; then
    log_note "  [PASS] $svc (pip-audit)"
    record_result "SECURITY" "$svc" "pip-audit" "PASS"
  else
    local vuln_count
    vuln_count=$(grep -ci "vuln" "$log" 2>/dev/null || echo "0")
    if [[ "$vuln_count" -gt 0 ]]; then
      log_note "  [WARN] $svc (pip-audit) — $vuln_count vulnerabilities (see pip_audit_${svc}.log)"
      record_result "SECURITY" "$svc" "pip-audit" "WARN" "$vuln_count vulnerabilities"
    else
      log_note "  [FAIL] $svc (pip-audit) — see pip_audit_${svc}.log"
      record_result "SECURITY" "$svc" "pip-audit" "FAIL"
    fi
  fi
}

run_security_npm_audit() {
  local log="$REPORT_DIR/npm_audit_frontend.log"

  if ! docker ps --format "{{.Names}}" | grep -q "curatore-frontend"; then
    log_note "  [SKIP] frontend (npm audit) — container not running"
    return 0
  fi

  log_note "  🔎 frontend (npm audit) ..."
  local code=0
  docker exec curatore-frontend npm audit --omit=dev >"$log" 2>&1 || code=$?

  if [[ $code -eq 0 ]]; then
    log_note "  [PASS] frontend (npm audit)"
    record_result "SECURITY" "frontend" "npm-audit" "PASS"
  else
    local vuln_line
    vuln_line=$(grep -i "vulnerabilit" "$log" | tail -1 || true)
    if [[ -n "$vuln_line" ]]; then
      log_note "  [WARN] frontend (npm audit) — $vuln_line"
      record_result "SECURITY" "frontend" "npm-audit" "WARN" "$vuln_line"
    else
      log_note "  [FAIL] frontend (npm audit) — see npm_audit_frontend.log"
      record_result "SECURITY" "frontend" "npm-audit" "FAIL"
    fi
  fi
}

run_security_phase() {
  print_header "Phase: Security Scanning"

  if [[ "$SKIP_SECURITY" == "1" ]]; then
    log_note "  [SKIP] Security scanning (SKIP_SECURITY=1)"
    return 0
  fi

  # Bandit (Python SAST)
  should_run_service "backend"          && run_security_bandit "backend"          "$BACKEND_DIR"    "backend"
  should_run_service "document-service" && run_security_bandit "document-service" "$DOCSVC_DIR"     "document-service"
  should_run_service "playwright"       && run_security_bandit "playwright"       "$PLAYWRIGHT_DIR" "playwright"
  should_run_service "mcp"              && run_security_bandit "mcp"              "$MCP_DIR"        "mcp"

  # pip-audit (Python deps)
  should_run_service "backend"          && run_security_pip_audit "backend"          "$BACKEND_DIR"    "backend"
  should_run_service "document-service" && run_security_pip_audit "document-service" "$DOCSVC_DIR"     "document-service"
  should_run_service "playwright"       && run_security_pip_audit "playwright"       "$PLAYWRIGHT_DIR" "playwright"
  should_run_service "mcp"              && run_security_pip_audit "mcp"              "$MCP_DIR"        "mcp"

  # npm audit (Node deps)
  should_run_service "frontend"         && run_security_npm_audit

  return 0
}

# -------- Phase 4: Tests + Coverage --------

run_test_backend() {
  local log="$REPORT_DIR/test_backend.log"

  log_note "  🧪 backend (pytest) ..."
  local code=0
  # Backend layout: compose context is curatore-backend/, source in backend/app, tests in backend/tests
  (cd "$BACKEND_DIR" && docker compose run --rm --no-deps --user root \
    -e USE_CELERY=false \
    -v "./backend/tests:/app/tests" \
    -v "./backend/requirements-dev.txt:/app/requirements-dev.txt" \
    --entrypoint="" backend \
    sh -c "pip install -q -r requirements-dev.txt >/dev/null 2>&1 && python -m pytest tests -v \
      --cov=app --cov-report=term-missing --cov-report=html:/app/tests/coverage_html" \
  ) >"$log" 2>&1 || code=$?

  # Extract test summary
  local summary_line
  summary_line=$(grep -E "=.*(passed|failed|error).*=" "$log" | tail -1 || true)
  local coverage_pct=""
  local coverage_line
  coverage_line=$(grep -E "^TOTAL\s+" "$log" | tail -1 || true)
  if [[ -n "$coverage_line" ]]; then
    coverage_pct=$(echo "$coverage_line" | awk '{print $NF}')
  fi

  if [[ $code -eq 0 ]]; then
    local note="${summary_line:-all tests passed}"
    [[ -n "$coverage_pct" ]] && note="$note ($coverage_pct coverage)"
    log_note "  [PASS] backend — $note"
    record_result "TESTS" "backend" "pytest" "PASS" "$note"
  else
    log_note "  [FAIL] backend (exit $code) — see test_backend.log"
    [[ -n "$summary_line" ]] && log_note "         $summary_line"
    record_result "TESTS" "backend" "pytest" "FAIL" "${summary_line:-exit $code}"
  fi
}

run_test_python_service() {
  local svc="$1"
  local compose_dir="$2"
  local compose_svc="$3"
  shift 3
  # Remaining args are extra flags for docker compose run (e.g., -e KEY=VALUE)
  local log="$REPORT_DIR/test_${svc}.log"

  if [[ ! -d "$compose_dir" ]]; then
    log_note "  [SKIP] $svc — directory not found"
    return 0
  fi
  if [[ ! -d "$compose_dir/tests" ]]; then
    log_note "  [SKIP] $svc — no tests/ directory"
    return 0
  fi
  if [[ ! -f "$compose_dir/requirements-dev.txt" ]]; then
    log_note "  [SKIP] $svc — no requirements-dev.txt"
    return 0
  fi

  log_note "  🧪 $svc (pytest) ..."
  local code=0
  (cd "$compose_dir" && docker compose run --rm --no-deps --user root \
    "$@" \
    -v "./tests:/app/tests" \
    -v "./requirements-dev.txt:/app/requirements-dev.txt" \
    --entrypoint="" "$compose_svc" \
    sh -c "pip install -q -r requirements-dev.txt >/dev/null 2>&1 && python -m pytest tests -v \
      --cov=app --cov-report=term-missing" \
  ) >"$log" 2>&1 || code=$?

  # Extract test summary
  local summary_line
  summary_line=$(grep -E "=.*(passed|failed|error).*=" "$log" | tail -1 || true)
  local coverage_pct=""
  local coverage_line
  coverage_line=$(grep -E "^TOTAL\s+" "$log" | tail -1 || true)
  if [[ -n "$coverage_line" ]]; then
    coverage_pct=$(echo "$coverage_line" | awk '{print $NF}')
  fi

  if [[ $code -eq 0 ]]; then
    local note="${summary_line:-all tests passed}"
    [[ -n "$coverage_pct" ]] && note="$note ($coverage_pct coverage)"
    log_note "  [PASS] $svc — $note"
    record_result "TESTS" "$svc" "pytest" "PASS" "$note"
  else
    log_note "  [FAIL] $svc (exit $code) — see test_${svc}.log"
    [[ -n "$summary_line" ]] && log_note "         $summary_line"
    record_result "TESTS" "$svc" "pytest" "FAIL" "${summary_line:-exit $code}"
  fi
}

run_test_frontend() {
  local log="$REPORT_DIR/test_frontend.log"

  if ! docker ps --format "{{.Names}}" | grep -q "curatore-frontend"; then
    log_note "  [SKIP] frontend — container not running"
    return 0
  fi

  log_note "  🧪 frontend (jest) ..."
  local code=0
  docker exec curatore-frontend npx jest --ci --coverage >"$log" 2>&1 || code=$?

  local summary_line
  summary_line=$(grep -E "Tests:" "$log" | head -1 || true)

  if [[ $code -eq 0 ]]; then
    log_note "  [PASS] frontend — ${summary_line:-all tests passed}"
    record_result "TESTS" "frontend" "jest" "PASS" "${summary_line:-}"
  else
    log_note "  [FAIL] frontend (exit $code) — see test_frontend.log"
    [[ -n "$summary_line" ]] && log_note "         $summary_line"
    record_result "TESTS" "frontend" "jest" "FAIL" "${summary_line:-exit $code}"
  fi
}

run_test_phase() {
  print_header "Phase: Tests + Coverage"

  if [[ "$SKIP_TESTS" == "1" ]]; then
    log_note "  [SKIP] Tests (SKIP_TESTS=1)"
    return 0
  fi

  should_run_service "backend"          && run_test_backend
  should_run_service "document-service" && run_test_python_service "document-service" "$DOCSVC_DIR"     "document-service"
  should_run_service "playwright"       && run_test_python_service "playwright"       "$PLAYWRIGHT_DIR" "playwright"
  should_run_service "mcp"              && run_test_python_service "mcp"              "$MCP_DIR"        "mcp" \
                                             -e SERVICE_API_KEY=test-key -e BACKEND_URL=http://backend:8000
  should_run_service "frontend"         && run_test_frontend

  return 0
}

# -------- Phase 5: Summary --------

print_summary() {
  print_header "Quality Check Summary"

  if (( ${#RESULTS[@]} == 0 )); then
    log_note "  No checks were executed."
    echo "============================================" | tee -a "$SUMMARY_FILE"
    return 0
  fi

  local pass_count=0 warn_count=0 fail_count=0
  local current_category=""

  for entry in "${RESULTS[@]}"; do
    IFS="|" read -r category svc tool status note <<< "$entry"
    if [[ "$category" != "$current_category" ]]; then
      current_category="$category"
      echo "  $category" | tee -a "$SUMMARY_FILE"
    fi
    local display="$svc ($tool)"
    case "$status" in
      PASS) ((pass_count++)); echo "    [PASS] $display" | tee -a "$SUMMARY_FILE" ;;
      WARN) ((warn_count++)); echo "    [WARN] $display${note:+ — $note}" | tee -a "$SUMMARY_FILE" ;;
      FAIL) ((fail_count++)); echo "    [FAIL] $display${note:+ — $note}" | tee -a "$SUMMARY_FILE" ;;
    esac
  done

  echo "" | tee -a "$SUMMARY_FILE"
  echo "  Totals: PASS=$pass_count, WARN=$warn_count, FAIL=$fail_count" | tee -a "$SUMMARY_FILE"
  echo "  Reports: $REPORT_DIR" | tee -a "$SUMMARY_FILE"
  echo "============================================" | tee -a "$SUMMARY_FILE"

  if [[ $fail_count -gt 0 ]]; then
    exit 1
  fi
}

# -------- Main --------

main() {
  print_header "Curatore Quality Check ($TIMESTAMP)"
  log_note "  Mode: $MODE"
  [[ -n "$SERVICE_FILTER" ]] && log_note "  Service: $SERVICE_FILTER"
  log_note "  Skip: lint=$SKIP_LINT, security=$SKIP_SECURITY, tests=$SKIP_TESTS"

  preflight

  if [[ "$MODE" == "all" || "$MODE" == "lint" ]] && [[ "$SKIP_LINT" != "1" ]]; then
    run_lint_phase
  fi

  if [[ "$MODE" == "all" || "$MODE" == "security" ]] && [[ "$SKIP_SECURITY" != "1" ]]; then
    run_security_phase
  fi

  if [[ "$MODE" == "all" || "$MODE" == "test" ]] && [[ "$SKIP_TESTS" != "1" ]]; then
    run_test_phase
  fi

  print_summary
}

main
