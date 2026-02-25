# CLAUDE.md — Curatore Local Development

Orchestration repo for running the full Curatore platform locally. Contains no application code — each service is a Git submodule.

## Getting Started

```bash
git clone --recurse-submodules https://github.com/Amivero-LLC/curatore-localdev.git
cd curatore-localdev
./scripts/bootstrap.sh
```

The bootstrap script prompts for API keys, generates configs, starts all services, and seeds the initial admin user from `.env` credentials. See [`.env.example`](.env.example) for all configurable variables.

To regenerate service configs after editing `.env`:
```bash
./scripts/generate-env.sh
```

## Dev Admin Credentials

The root `.env` contains admin credentials (`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_USERNAME`, `ADMIN_FULL_NAME`) that are automatically used to create the system admin user on fresh installs. This is a **development convenience** so you can perform system functions with consistent credentials across `bootstrap.sh` and `factory-reset.sh` cycles without re-entering them in the setup wizard each time.

- **Auto-seeded on fresh install** — prestart detects a new database and creates the admin from env vars
- **Idempotent** — skips if an admin already exists; safe to re-run
- **CLI fallback** — `docker exec curatore-backend python -m app.core.commands.seed --create-admin` for existing databases
- **Setup wizard still works** — if you prefer, clear the env vars and use http://localhost:3000/setup instead

To change the dev admin credentials, edit the root `.env` and re-run `./scripts/generate-env.sh`.

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

## API Authentication Cheat Sheet

Three auth methods — use the correct one on the **first call**. Do not trial-and-error.

### Method 1: JWT (Frontend Users → Backend)

```
POST /api/v1/admin/auth/login
Body: { "email_or_username": "...", "password": "..." }
Response: { "access_token": "<JWT>", "refresh_token": "<JWT>", "token_type": "bearer", "expires_in": 3600 }
```

Then on all subsequent requests:
```
Authorization: Bearer <access_token>
X-Organization-Id: <org-uuid>          # Required for org-scoped endpoints
```

- Access tokens expire in 60 min. Refresh via `POST /api/v1/admin/auth/refresh` with `{ "refresh_token": "..." }`
- Frontend auto-refreshes every 50 min and dispatches `auth:unauthorized` on 401s

### Method 2: API Key (Programmatic Access)

```
X-API-Key: cur_<64-hex-chars>
X-Organization-Id: <org-uuid>          # Required for org-scoped endpoints
```

- API keys are created via the UI or API, shown only once, stored as bcrypt hash
- Prefix `cur_` + 8-char prefix used for DB lookup, then full key is hash-verified

### Method 3: Delegated Auth (Service-to-Service, e.g., MCP → Backend)

**Incoming** (client → MCP gateway):
```
Authorization: Bearer <SERVICE_API_KEY>
X-OpenWebUI-User-Email: alice@company.com
X-Organization-Id: <org-uuid>          # Optional
```

**Outgoing** (MCP gateway → backend):
```
X-API-Key: <BACKEND_API_KEY>
X-On-Behalf-Of: alice@company.com
X-Correlation-ID: <uuid>
```

- Two separate keys: `SERVICE_API_KEY` (validates callers) vs `BACKEND_API_KEY` (authenticates to backend)
- Backend resolves user by email, scopes data to their org(s)

### Auth Priority Order (backend `get_current_user`)

1. If `ENABLE_AUTH=false` → returns first admin user (dev only)
2. JWT Bearer token (if `Authorization` header present)
3. Delegated auth (`X-API-Key` + `X-On-Behalf-Of` headers)
4. User API key (`X-API-Key` header alone)
5. None → 401 Unauthorized

### Critical Auth Rules for Agents

| Rule | Why |
|------|-----|
| **Always obtain a token before making API calls** | Don't make unauthenticated calls expecting to "discover" the auth method from 401 responses |
| **Use `X-Organization-Id` header for org-scoped endpoints** | Admin users have `organization_id=NULL` — org context must come from the header |
| **Never use `current_user.organization_id` directly** | Use dependency functions: `get_effective_org_id`, `get_current_org_id`, `get_user_org_ids` |
| **Extracted services use `Authorization: Bearer <SERVICE_API_KEY>`** | Document-service, playwright, MCP all follow this pattern; empty key = dev mode (no auth) |
| **Refresh tokens before they expire** | Don't wait for a 401 — proactively refresh at 50 min (frontend) or track `expires_in` |
| **Test auth uses mocked dependencies** | In pytest, override `get_current_user` with `mock_current_user` fixture — don't hit real auth |

### Key Auth Files

| File | Purpose |
|------|---------|
| `curatore-backend/backend/app/core/auth/auth_service.py` | JWT creation, password hashing, token decode |
| `curatore-backend/backend/app/dependencies.py` | All auth dependency functions (get_current_user, get_effective_org_id, etc.) |
| `curatore-backend/backend/docs/AUTH_ACCESS_MODEL.md` | Full auth & access control reference |
| `curatore-frontend/lib/api.ts` | Frontend API client (auto-attaches Bearer + org headers) |
| `curatore-frontend/lib/auth-context.tsx` | JWT lifecycle, auto-refresh, 401 handling |
| `curatore-mcp-service/app/middleware/auth.py` | MCP gateway incoming auth validation |
| `curatore-mcp-service/docs/DELEGATED_AUTH.md` | Delegated auth chain documentation |

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
9. **NEVER** consider a push complete without verifying GitHub Actions CI passes — use `gh run list` / `gh run watch` to confirm.
10. **NEVER** make API calls without first obtaining proper authentication — see [API Authentication Cheat Sheet](#api-authentication-cheat-sheet).

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

## Post-Push CI Verification

**After every push** to a submodule, verify GitHub Actions CI passes. Local `dev-check.sh` is necessary but not sufficient — CI runs in a clean Ubuntu environment that may catch issues local checks miss.

### Verification Steps

```bash
# After pushing to a submodule, check CI status:
gh run list --repo Amivero-LLC/<repo-name> --limit 5     # List recent runs
gh run watch --repo Amivero-LLC/<repo-name>               # Watch current run
gh run view <run-id> --repo Amivero-LLC/<repo-name> --log # View logs on failure
```

### CI Workflow Coverage

Each submodule has a `.github/workflows/ci.yml` that runs on push to `main` and on PRs. CI must include **all three phases** matching `dev-check.sh`:

| Phase | What Runs | CI Command |
|-------|-----------|------------|
| **Linting** | Ruff (Python) / ESLint (Frontend) | `ruff check app/ --line-length 120 --select E,F,W,I --ignore E501` |
| **Security** | Bandit (SAST) | `bandit -r app/ -ll` |
| **Tests** | pytest / Jest with coverage | `pytest tests/ -v --cov=app` |

### CI vs Local Differences to Watch For

| Issue | Why It Happens |
|-------|---------------|
| System dependency mismatch | CI uses Ubuntu; local may be macOS. LibreOffice, Tesseract, Playwright browsers differ |
| Python version difference | CI pins 3.12; local may vary |
| Missing env vars | CI has no `.env`; tests must work without real credentials |
| Network-dependent tests | CI has no Docker services; mock all external calls |
| Timing-sensitive failures | CI runners have variable performance; async tests may race |

### Anti-Patterns

9. **NEVER** consider a push complete without verifying CI passes — use `gh run list` / `gh run watch` to confirm.
10. **NEVER** push code that only passes `dev-check.sh` locally without also verifying the submodule's GitHub Actions CI.
11. **NEVER** merge a PR with failing CI checks — fix the failures first.

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
| Slow frontend hot reload (macOS) | In Docker Desktop Settings > General, ensure "VirtioFS" is selected as file sharing implementation |

## Clean Reinstall

```bash
./scripts/dev-down.sh
docker ps -a --filter "name=curatore-" --format "{{.ID}}" | xargs -r docker rm -f
docker images --format "{{.Repository}} {{.ID}}" | grep curatore | awk '{print $2}' | xargs -r docker rmi -f
docker volume ls --format "{{.Name}}" | grep curatore | xargs -r docker volume rm -f
docker network rm curatore-network
./scripts/dev-up.sh --with-postgres
# Admin user is auto-seeded from .env on fresh install — log in at http://localhost:3000
```
