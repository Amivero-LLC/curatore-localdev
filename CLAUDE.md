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
├── curatore-backend/           # FastAPI + Celery + Redis + PostgreSQL
├── curatore-frontend/          # Next.js 15 + React 19 + Tailwind
├── curatore-document-service/  # Document extraction (PDF, DOCX, etc.)
├── curatore-playwright-service/# Browser rendering for web scraping
├── curatore-mcp-service/       # AI tool gateway (MCP protocol)
├── curatore-minio-service/     # S3-compatible object storage
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

# Readiness (checks DB + Redis + MinIO)
curl http://localhost:8000/api/v1/admin/system/health/ready

# Comprehensive (all components, basic status)
curl http://localhost:8000/api/v1/admin/system/health/comprehensive

# Comprehensive with full diagnostics (requires auth)
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/admin/system/health/comprehensive
```

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

## Service Details

Each sub-repo has its own `CLAUDE.md` with service-specific guidance. Below is a cross-service summary.

### curatore-backend

**Tech:** FastAPI (Python 3.12), Celery, SQLAlchemy, PostgreSQL 16 + pgvector

**Key files:**
- `backend/app/main.py` — FastAPI entry point with startup sequence
- `backend/app/config.py` — Pydantic settings (reads `.env`)
- `config.yml` — Application configuration (LLM, search, services)
- `.env` — Secrets and infrastructure config
- `docker-compose.yml` — Backend + Worker + Beat + Redis + Postgres

**Startup sequence:**
1. Validate `config.yml` (fail-fast)
2. Pre-start checks: wait for PostgreSQL, Redis, MinIO (with retries)
3. Detect fresh install, run Alembic migrations
4. Auto-seed if fresh (system org, default org, data sources, scheduled tasks)
5. Queue registry, metadata baseline, procedure discovery
6. Connection sync, MinIO bucket init, LLM validation
7. `mark_startup_complete()` → readiness probe returns 200

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

### curatore-minio-service

**Tech:** MinIO (S3-compatible object storage)

**Purpose:** Stores uploaded files, extracted markdown, and temporary artifacts.

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

## Debugging

### Container Inspection

```bash
# See all running Curatore containers
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
Check that MinIO and Redis are running:
```bash
docker ps --filter "name=curatore-minio" --filter "name=curatore-redis"
```

**"relation does not exist" errors**
Migrations haven't run. The backend runs them automatically on startup, but you can force:
```bash
docker exec curatore-backend alembic upgrade head
```

**Frontend can't reach backend**
The frontend uses `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`). This is a browser-side URL, so it must be `localhost`, not `backend`.

**Worker not processing jobs**
Check worker logs and Redis connectivity:
```bash
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
