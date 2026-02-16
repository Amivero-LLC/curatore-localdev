# CLAUDE.md — Curatore Local Development

Development guidance for Claude Code working across the Curatore platform.

## What This Repo Is

`curatore-localdev` is the **orchestration layer** for running the full Curatore platform locally. It contains no application source code of its own — each service is a Git submodule pointing to its own repository. This repo provides:

- Git submodule registration for all services
- Startup/shutdown scripts (`scripts/dev-up.sh`, `scripts/dev-down.sh`)
- This CLAUDE.md as the authoritative cross-service development guide

## Architecture Overview

```
curatore-localdev/
├── curatore-backend/           # FastAPI + Celery + Redis + PostgreSQL + MinIO
├── curatore-frontend/          # Next.js 15 + React 19 + Tailwind
├── curatore-document-service/  # Document extraction (PDF, DOCX, etc.)
├── curatore-playwright-service/# Browser rendering for web scraping
├── curatore-mcp-service/       # AI tool gateway (MCP protocol)
└── scripts/                    # dev-up.sh, dev-down.sh, dev-logs.sh
```

### Network Topology

All services share a single Docker network: `curatore-network` (external, created by `dev-up.sh`).

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

Services reference each other by Docker container name on `curatore-network`:

| Container Name | Internal URL | Purpose |
|---------------|-------------|---------|
| `curatore-backend` / `backend` | `http://backend:8000` | API server |
| `curatore-postgres` / `postgres` | `postgres:5432` | Database |
| `curatore-redis` / `redis` | `redis:6379` | Celery broker + cache |
| `curatore-minio` / `minio` | `minio:9000` | Object storage |
| `curatore-document-service` / `document-service` | `http://document-service:8010` | Extraction |
| `curatore-playwright` / `playwright` | `http://playwright:8011` | Rendering |
| `curatore-mcp` / `mcp` | `http://mcp:8020` | AI gateway |
| `curatore-frontend` / `frontend` | `http://frontend:3000` | Web UI |

**Important:** Inter-service URLs use the Docker service name (e.g., `http://document-service:8010`), NOT `localhost`. The `localhost:PORT` URLs are for browser/developer access only.

---

## Quick Reference

### Starting & Stopping

```bash
# Start everything (with PostgreSQL)
./scripts/dev-up.sh --with-postgres

# Stop everything
./scripts/dev-down.sh

# View logs
./scripts/dev-logs.sh              # Backend
./scripts/dev-logs.sh worker       # Celery worker
./scripts/dev-logs.sh frontend     # Frontend
./scripts/dev-logs.sh all          # Everything

# Service status
./scripts/dev-status.sh
```

### Port Map

| Port | Service | Container |
|------|---------|-----------|
| 3000 | Frontend | curatore-frontend |
| 5432 | PostgreSQL | curatore-postgres |
| 6379 | Redis | curatore-redis |
| 8000 | Backend API | curatore-backend |
| 8010 | Document Service | curatore-document-service |
| 8011 | Playwright Service | curatore-playwright |
| 8020 | MCP Gateway | curatore-mcp |
| 9000 | MinIO S3 API | curatore-minio |
| 9001 | MinIO Console | curatore-minio |

### Health Checks

```bash
# Liveness (zero I/O, always 200)
curl http://localhost:8000/api/v1/admin/system/health/live

# Readiness (checks DB + Redis + MinIO + startup complete)
curl http://localhost:8000/api/v1/admin/system/health/ready

# Comprehensive (all components, basic status)
curl http://localhost:8000/api/v1/admin/system/health/comprehensive

# Comprehensive with full diagnostics (requires auth)
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/admin/system/health/comprehensive
```

All health endpoints are public (no auth for basic status). Authenticated requests return full diagnostics (tables, pool stats, connection URLs, etc.).

### Database Commands

```bash
# Seed admin user (first time)
docker exec curatore-backend python -m app.core.commands.seed --create-admin

# Run migrations manually
docker exec curatore-backend alembic upgrade head

# Create a new migration
docker exec curatore-backend alembic revision --autogenerate -m "description"

# Connect to PostgreSQL
docker exec -it curatore-postgres psql -U curatore -d curatore
```

---

## Startup Sequence & Hardening

### Docker Healthcheck & Dependency Chain

The backend `docker-compose.yml` enforces startup ordering via healthchecks and `depends_on` conditions:

| Container | Healthcheck | Starts After |
|-----------|------------|-------------|
| `redis` | `redis-cli ping` | — |
| `minio` | MinIO `/health/live` | — |
| `postgres` | `pg_isready` (profile-gated) | — |
| `backend` | `/api/v1/admin/system/health/ready` (90s start_period) | Redis healthy, MinIO healthy |
| `worker` | `celery inspect ping` | Redis healthy |
| `beat` | — | Redis healthy, Backend healthy |

The backend healthcheck uses the **readiness** endpoint (not liveness), so Docker won't report it as healthy until the full startup sequence completes.

### Backend Pre-Start Checks (`prestart.py`)

Before the FastAPI app accepts requests, `prestart.py` runs synchronously in a thread pool:

```
 1. Wait for PostgreSQL ── 30 retries × 2s = 60s max
 2. Wait for Redis ─────── 15 retries × 2s = 30s max
 3. Wait for MinIO ─────── 15 retries × 2s = 30s max (if USE_OBJECT_STORAGE=true)
 4. Detect fresh install ─ Check alembic_version table
 5. Schema setup:
    Fresh:    Base.metadata.create_all() + seed roles + create VIEWs + alembic stamp head
    Existing: alembic upgrade head (idempotent)
 6. Auto-seed if fresh ── system org, default org, data sources, scheduled tasks
    (System org failure is fatal — exit code 3)
 7. Print admin user creation instructions
```

### Full Startup Event Sequence (main.py)

After prestart completes:

```
 1. Config.yml validation (fail-fast)
 2. Pre-start checks (dependency waiting, migrations, seeding)    ← prestart.py
 3. Queue registry initialization
 4. Facet reference data baseline
 5. Metadata registry baseline sync
 6. Metadata validation
 7. Scheduled task baseline
 8. System org + procedure/pipeline discovery
 9. Connection sync from environment
10. System services sync from config.yml
11. MinIO bucket initialization
12. LLM status + embedding config validation
13. mark_startup_complete() → readiness probe returns 200
```

### Storage Initialization

`dev-up.sh` polls the backend readiness endpoint (`/health/ready`) for up to 5 minutes before running `init_storage.sh`. This creates three MinIO buckets with lifecycle policies:

| Bucket | Retention | Purpose |
|--------|-----------|---------|
| `curatore-uploads` | 30 days | File uploads |
| `curatore-processed` | 90 days | Extracted markdown |
| `curatore-temp` | 7 days | Temporary files |

### Fresh Install Behavior

On a brand-new database (no `alembic_version` table), prestart.py:

1. **Creates all tables** via `Base.metadata.create_all()` (SQLAlchemy models)
2. **Seeds reference data** — `admin` and `member` roles (required for user creation)
3. **Creates SQL VIEWs** — `unified_forecasts` (required for forecast queries)
4. **Stamps Alembic** — `alembic stamp head` marks all migrations as applied
5. **Auto-seeds** — system org (`__system__`), default org, data source config, scheduled tasks
6. **Logs instruction** — `Run python -m app.core.commands.seed --create-admin to create admin user`

Admin user creation is **always manual** for security.

**Reference data parity:** When adding a new Alembic migration that INSERTs reference data or creates SQL VIEWs, you MUST also update `_create_all_tables()` in `prestart.py` to maintain parity with the fresh install path.

---

## Service Details

Each sub-repo has its own `CLAUDE.md` with service-specific guidance. Below is a cross-service summary.

### curatore-backend

**Tech:** FastAPI (Python 3.12), Celery, SQLAlchemy, PostgreSQL 16 + pgvector

**Key files:**
- `backend/app/main.py` — FastAPI entry point with startup sequence
- `backend/app/config.py` — Pydantic settings (reads `.env`)
- `backend/app/core/commands/prestart.py` — Dependency waiting, fresh install detection, migrations
- `config.yml` — Application configuration (LLM, search, services)
- `.env` — Secrets and infrastructure config
- `docker-compose.yml` — Backend + Worker + Beat + Redis + MinIO + Postgres

**Three containers from one image:**
- `curatore-backend` — `uvicorn` serving the API
- `curatore-worker` — `celery worker` processing background jobs
- `curatore-beat` — `celery beat` scheduler

**Configuration convention:**
- `.env` — Secrets and Docker infrastructure (credentials, service endpoints within Compose)
- `config.yml` — Application behavior (feature flags, LLM routing, search tuning, external service discovery)
- Secrets go in `.env`, referenced by `config.yml` via `${VAR_NAME}` syntax

### curatore-frontend

**Tech:** Next.js 15.5, TypeScript, React 19, Tailwind CSS

**Key patterns:**
- API client in `lib/api.ts` with TypeScript interfaces
- Pages under `app/` directory (App Router)
- Components in `components/` with feature-based organization

### curatore-document-service

**Tech:** FastAPI (Python 3.12), LibreOffice, WeasyPrint

**Purpose:** Extracts text/markdown from uploaded documents (PDF, DOCX, XLSX, etc.). The backend POSTs files here; this service handles triage and engine selection.

### curatore-playwright-service

**Tech:** FastAPI (Python 3.12), Playwright

**Purpose:** Browser rendering for JavaScript-heavy web pages during web scraping.

### curatore-mcp-service

**Tech:** FastAPI (Python 3.12)

**Purpose:** MCP (Model Context Protocol) gateway for Claude Desktop, Open WebUI, and other AI clients. Proxies tool calls to the backend API.

---

## Cross-Service Development Patterns

### Adding a New Service

1. Create a new repository: `curatore-<name>-service`
2. Follow the pattern:
   - `docker-compose.yml` with `networks: curatore-network: external: true`
   - `Dockerfile` (Python 3.12-slim for Python services)
   - `.env.example` with documented variables
   - `.gitignore` excluding `.env`
   - `README.md` and `CLAUDE.md`
3. Register as a submodule: `git submodule add <url> curatore-<name>-service`
4. Add startup to `scripts/dev-up.sh`
5. Add teardown to `scripts/dev-down.sh`

### Service Authentication Pattern

All extracted services use an optional `SERVICE_API_KEY` pattern:
- **Empty/unset** → dev mode, no authentication required
- **Set to a value** → validates `Authorization: Bearer <key>` on every request

For local development, keys are left empty or use dev defaults (e.g., `doc-svc-dev-key-2026`).

### Hot Reload

All services mount source code as Docker volumes for live reloading:
- **Python services:** `./app:/app/app` + `uvicorn --reload` or `watchmedo auto-restart`
- **Frontend:** `.:/app` + `npm run dev`
- **Backend alembic:** `./backend/alembic:/app/alembic` (migrations reload too)

Changes to source files are reflected immediately without rebuilding containers.

### Rebuilding After Dependency Changes

When `requirements.txt`, `package.json`, or `Dockerfile` changes:

```bash
# Rebuild a specific service
cd curatore-backend && docker compose up -d --build

# Rebuild all
./scripts/dev-down.sh && ./scripts/dev-up.sh --with-postgres
```

### Working with Git Submodules

```bash
# Pull latest for all services
git submodule update --remote

# Pull latest for one service
cd curatore-backend && git pull origin main

# After someone else updates submodule refs
git submodule update --init --recursive

# Check submodule status
git submodule status
```

**Important:** When you make changes inside a submodule directory, you commit those changes in that submodule's repository. Then in curatore-localdev, `git add curatore-backend` and commit to update the submodule reference.

---

## Clean Reinstall

To tear down everything and start completely fresh:

```bash
# Stop all services
./scripts/dev-down.sh

# Remove all curatore containers, images, volumes, and network
docker ps -a --filter "name=curatore-" --format "{{.ID}}" | xargs -r docker rm -f
docker images --format "{{.Repository}} {{.ID}}" | grep curatore | awk '{print $2}' | xargs -r docker rmi -f
docker volume ls --format "{{.Name}}" | grep curatore | xargs -r docker volume rm -f
docker network rm curatore-network

# Start fresh
./scripts/dev-up.sh --with-postgres

# Seed admin user
docker exec curatore-backend python -m app.core.commands.seed --create-admin
```

---

## Debugging

### Container Inspection

```bash
# See all running Curatore containers (with health status)
docker ps --filter "name=curatore-"

# Shell into a container
docker exec -it curatore-backend bash

# Check container resource usage
docker stats --filter "name=curatore-" --no-stream
```

### Common Issues

**"curatore-network not found"**
```bash
docker network create curatore-network
```

**Backend won't start (dependency timeout)**
Check that MinIO, Redis, and PostgreSQL are running and healthy:
```bash
docker ps --filter "name=curatore-minio" --filter "name=curatore-redis" --filter "name=curatore-postgres"
```

**"relation does not exist" errors**
On existing databases, run migrations:
```bash
docker exec curatore-backend alembic upgrade head
```
On fresh installs, this is handled automatically by `prestart.py`.

**Frontend can't reach backend**
The frontend uses `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`). This is a browser-side URL, so it must be `localhost`, not `backend`.

**Worker not processing jobs**
Check worker health and logs:
```bash
docker ps --filter "name=curatore-worker"  # Should show (healthy)
./scripts/dev-logs.sh worker
docker exec curatore-redis redis-cli ping
```

---

## API Quick Reference

```
Admin:
  Health:      GET /api/v1/admin/system/health/{live,ready,comprehensive,database,redis,...}
  Auth:        POST /api/v1/admin/auth/login, /register
  Users:       GET /api/v1/admin/users, PUT /users/{id}

Data:
  Assets:      GET/POST /api/v1/data/assets, DELETE /assets/{id}
  Search:      POST /api/v1/data/search
  Collections: GET/POST /api/v1/data/collections
  SAM.gov:     GET /api/v1/data/sam/searches, /solicitations
  Forecasts:   GET /api/v1/data/forecasts

Ops:
  Runs:        GET /api/v1/ops/runs, GET /runs/{id}/logs
  Queue:       GET /api/v1/ops/queue/jobs

CWR:
  Functions:   GET /api/v1/cwr/functions
  Procedures:  GET /api/v1/cwr/procedures, POST /procedures/{slug}/run
  Pipelines:   GET /api/v1/cwr/pipelines
```

Full API docs: http://localhost:8000/docs

---

## Testing

```bash
# Backend tests (from inside container)
docker exec curatore-backend python -m pytest tests -v

# Frontend tests (from inside container)
docker exec curatore-frontend npm test

# Or run backend tests with local venv
cd curatore-backend && backend/.venv/bin/python -m pytest backend/tests -v
```
