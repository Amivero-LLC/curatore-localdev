# CLAUDE.md — Curatore Local Development

Orchestration repo for running the full Curatore platform locally. Contains no application code — each service is a Git submodule.

## Getting Started

```bash
git clone --recurse-submodules https://github.com/Amivero-LLC/curatore-localdev.git
cd curatore-localdev
./scripts/bootstrap.sh
```

The bootstrap script prompts for API keys, generates configs, and starts all services. On first visit to http://localhost:3000, a setup wizard guides you through creating the initial admin account. See [`.env.example`](.env.example) for all configurable variables.

To regenerate service configs after editing `.env`:
```bash
./scripts/generate-env.sh
```

## Key Commands

```bash
./scripts/dev-up.sh --with-postgres    # Start everything
./scripts/dev-down.sh                  # Stop everything
./scripts/dev-logs.sh                  # Backend logs
./scripts/dev-logs.sh worker           # All worker logs (documents + general)
./scripts/dev-logs.sh worker-documents # Document extraction worker logs
./scripts/dev-logs.sh worker-general   # Integration sync worker logs
./scripts/dev-logs.sh all              # All logs
./scripts/dev-status.sh               # Service status
./scripts/dev-check.sh                 # Full quality check (lint + security + tests)
./scripts/dev-check.sh --lint-only     # Linting only
./scripts/dev-check.sh --service=backend  # Single service only
docker exec curatore-backend alembic upgrade head  # Run migrations
docker exec curatore-backend python -m app.core.commands.seed --create-admin  # CLI admin seed (alternative to setup wizard)
```

## Platform Architecture

```
curatore-localdev/
├── curatore-backend/           # FastAPI + Celery + Redis + PostgreSQL + MinIO
├── curatore-frontend/          # Next.js 15 + React 19 + Tailwind
├── curatore-document-service/  # Document extraction (PDF, DOCX, etc.)
├── curatore-playwright-service/# Browser rendering for web scraping
├── curatore-mcp-service/       # AI tool gateway (MCP protocol)
└── scripts/                    # dev-up.sh, dev-down.sh, dev-logs.sh, dev-check.sh
```

### Network Topology

All services share `curatore-network` (external Docker network, created by `dev-up.sh`).

```
                    ┌─────────────────────────────────────────────┐
                    │              curatore-network                │
                    │                                             │
  :3000 ──── frontend ──────┐                                    │
                             │                                    │
  :8000 ──── backend ───────┼──── postgres (:5432)               │
             │  │  │        │                                    │
  :8020 ──── mcp ──┘  │     ├──── redis (:6379)                  │
                      │     │                                    │
             worker ──┘     ├──── minio (:9000/:9001)            │
             beat ──────────┤                                    │
                            ├──── document-service (:8010)       │
                            └──── playwright (:8011)             │
                    └─────────────────────────────────────────────┘
```

### Service Discovery (container names)

Services reference each other by Docker container name, **not** `localhost`:

| Container Name | Internal URL | Purpose |
|---------------|-------------|---------|
| `backend` | `http://backend:8000` | API server |
| `postgres` | `postgres:5432` | Database |
| `redis` | `redis:6379` | Celery broker + cache |
| `minio` | `minio:9000` | Object storage |
| `document-service` | `http://document-service:8010` | Extraction |
| `playwright` | `http://playwright:8011` | Rendering |
| `mcp` | `http://mcp:8020` | AI gateway |
| `frontend` | `http://frontend:3000` | Web UI |

## Cross-Service Development Rules

1. **API changes cascade** — When changing backend API endpoints, update: frontend `lib/api.ts`, MCP service contract converter, and docs
2. **Config split** — `.env` = secrets + Docker infrastructure; `config.yml` = application behavior + external service discovery (including SAM.gov, Microsoft Graph, LLM, extraction, playwright). See [backend CLAUDE.md](curatore-backend/CLAUDE.md)
3. **Inter-service URLs** — Always use Docker container names (e.g., `http://document-service:8010`), never `localhost`. `localhost:PORT` is for browser/developer access only
4. **Migration parity** — When adding Alembic migrations that INSERT reference data or create VIEWs, also update `prestart.py` `_create_all_tables()` for fresh install parity
5. **Four containers, one image** — Backend, worker-documents, worker-general, and beat all run from the same Docker image
6. **Service auth pattern** — All extracted services use optional `SERVICE_API_KEY`: empty = dev mode, set = validates `Authorization: Bearer <key>`
7. **Hot reload** — Python services mount `./app:/app/app` + `uvicorn --reload`; frontend mounts `.:/app` + `npm run dev`. No rebuild needed for source changes.
8. **Push-based health monitoring** — Three patterns, zero inter-service polling. See [Health Monitoring](docs/OVERVIEW.md#health-monitoring) for full details.
   - **Core infrastructure** (backend, database, redis, storage, workers, beat): backend/worker processes write their own heartbeats every 30s.
   - **Extracted services** (document-service, playwright, mcp): each service self-registers via `app/services/heartbeat_writer.py` every 30s. The backend does **not** poll them.
   - **External APIs** (LLM, SharePoint): event-driven via `ExternalServiceMonitor` — check on startup, consumers report errors/success, recovery poll only when unhealthy.

## Cross-Service Anti-Patterns

1. **NEVER** use `current_user.organization_id` directly — admin users have `NULL`. Use dependency functions.
2. **NEVER** hardcode LLM model names — always read from `config.yml`. No fallback defaults.
3. **NEVER** add silent config fallbacks — fail visibly with clear errors.
4. **NEVER** commit `.env` files — they contain secrets.
5. **NEVER** use `localhost` in inter-service Docker URLs.
6. **NEVER** assign users to `__system__` org — it's for CWR procedure ownership only.
7. **NEVER** commit code without running `./scripts/dev-check.sh` (or the appropriate `--service=` variant) and confirming all phases pass. Fix failures before committing.
8. **NEVER** suppress security findings (`# nosec`, `# noqa`) or skip tests (`@pytest.mark.skip`) without explicit justification in a comment explaining why.

## Pre-Commit Quality Gates

**Before every commit** — in localdev or any submodule — run the relevant quality checks and fix all failures. Do not commit code that fails linting, security scanning, or tests.

### Quick Reference

```bash
./scripts/dev-check.sh                       # Full sweep: lint + security + tests (all services)
./scripts/dev-check.sh --service=backend     # Single service only
./scripts/dev-check.sh --lint-only           # Linting only
./scripts/dev-check.sh --security-only       # Security only
./scripts/dev-check.sh --test-only           # Tests only
```

### What Must Pass

All three phases must pass before committing. Warnings (WARN) are acceptable; failures (FAIL) are not.

| Phase | Tool | Services | What It Checks |
|-------|------|----------|----------------|
| **Linting** | Ruff | backend, document-service, playwright, mcp | Python style: E (errors), F (pyflakes), W (warnings), I (isort) — line-length 120 |
| **Linting** | ESLint | frontend | Next.js + TypeScript rules (`.eslintrc.json`) |
| **Security (SAST)** | Bandit | backend, document-service, playwright, mcp | Python static analysis — medium + high severity (`-ll`) |
| **Security (Deps)** | pip-audit | backend, document-service, playwright, mcp | Known CVEs in installed Python packages |
| **Security (Deps)** | npm audit | frontend | Known vulnerabilities in production Node dependencies (`--omit=dev`) |
| **Tests** | pytest | backend, document-service, playwright, mcp | Full test suite with coverage (`--cov=app`) |
| **Tests** | Jest | frontend | Full test suite with coverage (`--ci --coverage`) |

### When to Run What

| Change Scope | Minimum Check |
|-------------|--------------|
| Single Python service (e.g., backend only) | `./scripts/dev-check.sh --service=backend` |
| Single frontend change | `./scripts/dev-check.sh --service=frontend` |
| Cross-service changes (API contract, shared types) | `./scripts/dev-check.sh` (full sweep) |
| Documentation-only changes | No check required |
| Docker/compose config changes | `./scripts/dev-check.sh --test-only` (verify services still start and pass) |

### Service-to-Check Mapping

When working inside a submodule, use `--service=` to target just that service:

| Submodule Directory | `--service=` Value |
|--------------------|-------------------|
| `curatore-backend/` | `backend` |
| `curatore-document-service/` | `document-service` |
| `curatore-playwright-service/` | `playwright` |
| `curatore-mcp-service/` | `mcp` |
| `curatore-frontend/` | `frontend` |

### Fixing Common Failures

| Failure | How to Fix |
|---------|-----------|
| Ruff import order (I001) | Reorder imports: stdlib → third-party → local, separated by blank lines |
| Ruff unused import (F401) | Remove the unused import |
| Ruff undefined name (F821) | Add the missing import or fix the typo |
| Bandit finding (medium/high) | Address the security issue — do not suppress with `# nosec` without justification |
| pip-audit / npm audit vulnerability | Update the affected package if a fix is available; document if no fix exists yet |
| pytest failure | Fix the failing test or the code it tests — do not skip tests with `@pytest.mark.skip` without justification |
| ESLint error | Fix per the rule; unused vars can use `_` prefix if intentionally unused |

### Reports

All check results are written to `logs/quality_reports/<TIMESTAMP>/`. Review individual log files (e.g., `lint_backend.log`, `bandit_mcp.log`, `test_frontend.log`) for details on failures.

## Submodule Workflow

```bash
# Make changes in a submodule
cd curatore-backend && git add -A && git commit -m "message" && git push

# Update submodule reference in localdev
cd .. && git add curatore-backend && git commit -m "Update backend ref"

# Pull all submodule updates
git submodule update --remote
```

## Service-Specific Guidance

| Service | CLAUDE.md | Key Info |
|---------|-----------|----------|
| Backend | [curatore-backend/CLAUDE.md](curatore-backend/CLAUDE.md) | API, workers, database, CWR, search |
| Frontend | [curatore-frontend/CLAUDE.md](curatore-frontend/CLAUDE.md) | Next.js, API client, components |
| Document Service | [curatore-document-service/CLAUDE.md](curatore-document-service/CLAUDE.md) | Stateless extraction/generation |
| Playwright Service | [curatore-playwright-service/CLAUDE.md](curatore-playwright-service/CLAUDE.md) | Browser rendering |
| MCP Service | [curatore-mcp-service/CLAUDE.md](curatore-mcp-service/CLAUDE.md) | AI tool gateway |

## Platform Documentation

Cross-cutting docs live in [`docs/`](docs/INDEX.md). Service-specific docs stay in each repo.

| Document | Description |
|----------|-------------|
| [Platform Overview](docs/OVERVIEW.md) | Architecture, data flow, auth flows (Mermaid) |
| [Documentation Index](docs/INDEX.md) | Master map of all docs across all repos |
| [Configuration](docs/CONFIGURATION.md) | .env vs config.yml philosophy |
| [Document Processing](docs/DOCUMENT_PROCESSING.md) | Upload → extraction → indexing pipeline |
| [Extraction Engines](docs/EXTRACTION_SERVICES.md) | Triage, engine comparison |
| [Embedding Models & pgvector](docs/EMBEDDING_MODELS.md) | Supported models, dimension auto-resolution, switching models |
| [Data Connections](docs/DATA_CONNECTIONS.md) | Adding new integrations |

## Quick Debugging

| Problem | Fix |
|---------|-----|
| `curatore-network not found` | `docker network create curatore-network` |
| Backend won't start (dependency timeout) | Check `docker ps --filter "name=curatore-"` for unhealthy containers |
| `relation does not exist` on existing DB | `docker exec curatore-backend alembic upgrade head` |
| Frontend can't reach backend | `NEXT_PUBLIC_API_URL` must be `http://localhost:8000` (browser-side URL) |
| Worker not processing jobs | Check `docker ps --filter "name=curatore-worker"` and `./scripts/dev-logs.sh worker`. Two pools: `worker-documents` (extraction/priority/maintenance), `worker-general` (syncs) |
| Check all service heartbeats | `docker exec curatore-redis redis-cli -n 2 KEYS "curatore:heartbeat:*"` |
| Check specific service heartbeat | `docker exec curatore-redis redis-cli -n 2 GET "curatore:heartbeat:backend"` |
| Service shows unhealthy after restart | Heartbeat writers update within 30s. Check freshness thresholds in `heartbeat_service.py` |
| SAM.gov pages show "configuration required" | Set `SAM_API_KEY` in root `.env`, run `./scripts/generate-env.sh`, restart services. Verify `config.yml` has `sam: enabled: true` |

## Clean Reinstall

```bash
./scripts/dev-down.sh
docker ps -a --filter "name=curatore-" --format "{{.ID}}" | xargs -r docker rm -f
docker images --format "{{.Repository}} {{.ID}}" | grep curatore | awk '{print $2}' | xargs -r docker rmi -f
docker volume ls --format "{{.Name}}" | grep curatore | xargs -r docker volume rm -f
docker network rm curatore-network
./scripts/dev-up.sh --with-postgres
# Open http://localhost:3000 to create admin via setup wizard
# Or use CLI: docker exec curatore-backend python -m app.core.commands.seed --create-admin
```
