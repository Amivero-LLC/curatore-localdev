# Curatore Local Development

Master repository for running the full Curatore platform locally. Each service lives in its own repository and is registered as a Git submodule.

## Architecture

```
curatore-localdev/
├── curatore-backend/           # FastAPI API + Celery workers + Redis + MinIO + PostgreSQL
├── curatore-frontend/          # Next.js 15 web application
├── curatore-document-service/  # Document extraction microservice
├── curatore-playwright-service/# Browser rendering microservice
├── curatore-mcp-service/       # AI tool gateway (MCP protocol)
└── scripts/                    # Orchestration scripts
```

All services communicate over a shared Docker network (`curatore-network`).

## Prerequisites

- **Docker** and **Docker Compose** (v2+)
- **Git** with submodule support
- An **OpenAI API key** (or compatible LLM endpoint)

## Quick Start

### 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/Amivero-LLC/curatore-localdev.git
cd curatore-localdev
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

### 2. Configure secrets

```bash
# Backend (required)
cp curatore-backend/.env.example curatore-backend/.env
cp curatore-backend/config.yml.example curatore-backend/config.yml
# Edit .env and config.yml with your API keys (at minimum: OPENAI_API_KEY)
```

**Two files, distinct responsibilities:**
- **`.env`** — Infrastructure & secrets: credentials, database URLs, MinIO keys
- **`config.yml`** — Application behavior: LLM models/routing, service discovery, search tuning

### 3. Start everything

```bash
./scripts/dev-up.sh --with-postgres
```

This starts all services in dependency order:

1. Docker network (`curatore-network`)
2. Backend infrastructure (Redis, MinIO, PostgreSQL) with health verification
3. Backend API + Celery workers (waits for Redis + MinIO healthy)
4. Celery Beat scheduler (waits for backend healthy)
5. Document Service
6. Playwright Service
7. Frontend
8. MCP Gateway
9. Storage bucket initialization (waits for backend readiness probe)

On **first run**, the backend automatically:
- Detects the fresh database (no Alembic version table)
- Creates all tables and SQL views
- Seeds reference data (roles)
- Creates the system org, default org, and default data sources
- Stamps Alembic to head

### 4. Create admin user (first time only)

```bash
docker exec curatore-backend python -m app.core.commands.seed --create-admin
```

### 5. Open the app

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |
| Document Service | http://localhost:8010 |
| Playwright Service | http://localhost:8011 |
| MCP Gateway | http://localhost:8020 |

Default login: `admin@example.com` / `changeme`

## Startup Hardening

The platform uses multiple layers to ensure reliable startup:

**Docker healthchecks** — Each infrastructure service has a healthcheck, and `depends_on` conditions enforce ordering:

| Container | Healthcheck | Depends On |
|-----------|------------|-----------|
| `curatore-redis` | `redis-cli ping` | — |
| `curatore-minio` | MinIO `/health/live` | — |
| `curatore-postgres` | `pg_isready` | — |
| `curatore-backend` | `/api/v1/admin/system/health/ready` | Redis (healthy), MinIO (healthy) |
| `curatore-worker` | `celery inspect ping` | Redis (healthy) |
| `curatore-beat` | — | Redis (healthy), Backend (healthy) |

**Pre-start checks** (`prestart.py`) — Before the backend accepts requests:
1. Waits for PostgreSQL (30 retries x 2s), Redis (15 x 2s), MinIO (15 x 2s)
2. Detects fresh install vs. existing database
3. Runs schema setup (fresh: `create_all` + stamp; existing: `alembic upgrade head`)
4. Auto-seeds baseline data on fresh install
5. `mark_startup_complete()` gates the readiness probe

**Storage initialization** — `dev-up.sh` polls the backend readiness endpoint (up to 5 minutes) before running `init_storage.sh`, ensuring MinIO buckets are created reliably.

## Scripts

| Script | Purpose |
|--------|---------|
| `./scripts/dev-up.sh` | Start all services |
| `./scripts/dev-up.sh --with-postgres` | Start with PostgreSQL |
| `./scripts/dev-up.sh --with-docling` | Start with Docling extraction engine |
| `./scripts/dev-up.sh --all` | Start with all optional services |
| `./scripts/dev-down.sh` | Stop all services |
| `./scripts/dev-logs.sh` | View backend logs |
| `./scripts/dev-logs.sh [service]` | View specific service logs |
| `./scripts/dev-status.sh` | Show running service status |

## Health Checks

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

All health endpoints are public (no auth required for basic status). Authenticated requests get full diagnostics.

## Port Map

| Port | Service |
|------|---------|
| 3000 | Frontend |
| 5432 | PostgreSQL |
| 6379 | Redis |
| 8000 | Backend API |
| 8010 | Document Service |
| 8011 | Playwright Service |
| 8020 | MCP Gateway |
| 9000 | MinIO S3 API |
| 9001 | MinIO Console |

## Service Repositories

| Service | Repository |
|---------|-----------|
| Backend | [curatore-backend](https://github.com/Amivero-LLC/curatore-backend) |
| Frontend | [curatore-frontend](https://github.com/Amivero-LLC/curatore-frontend) |
| Document Service | [curatore-document-service](https://github.com/Amivero-LLC/curatore-document-service) |
| Playwright Service | [curatore-playwright-service](https://github.com/Amivero-LLC/curatore-playwright-service) |
| MCP Gateway | [curatore-mcp-service](https://github.com/Amivero-LLC/curatore-mcp-service) |

## Working with Submodules

```bash
# Pull latest changes for all submodules
git submodule update --remote

# Pull latest for a specific service
cd curatore-backend && git pull origin main

# After cloning on a new machine
git submodule update --init --recursive
```

**Important:** When you make changes inside a submodule directory, commit those changes in that submodule's repository first. Then in curatore-localdev, run `git add curatore-backend` and commit to update the submodule reference.

## Clean Reinstall

To tear down everything and start fresh:

```bash
# Stop all services
./scripts/dev-down.sh

# Remove all containers, images, volumes, and network
docker ps -a --filter "name=curatore-" --format "{{.ID}}" | xargs -r docker rm -f
docker images --format "{{.Repository}} {{.ID}}" | grep curatore | awk '{print $2}' | xargs -r docker rmi -f
docker volume ls --format "{{.Name}}" | grep curatore | xargs -r docker volume rm -f
docker network rm curatore-network

# Start fresh
./scripts/dev-up.sh --with-postgres

# Seed admin user
docker exec curatore-backend python -m app.core.commands.seed --create-admin
```

## Stopping Services

```bash
# Stop everything
./scripts/dev-down.sh

# Remove the shared network (optional)
docker network rm curatore-network
```

## Debugging

```bash
# See all running Curatore containers (with health status)
docker ps --filter "name=curatore-"

# Shell into a container
docker exec -it curatore-backend bash

# Check container resource usage
docker stats --filter "name=curatore-" --no-stream

# Connect to PostgreSQL
docker exec -it curatore-postgres psql -U curatore -d curatore

# Check Redis
docker exec curatore-redis redis-cli ping

# Check Celery workers
docker exec curatore-worker celery -A app.celery_app inspect active
```

### Common Issues

**"curatore-network not found"** — The network is created by `dev-up.sh`. Create it manually:
```bash
docker network create curatore-network
```

**Backend won't start (dependency timeout)** — Check that infrastructure is running:
```bash
docker ps --filter "name=curatore-minio" --filter "name=curatore-redis" --filter "name=curatore-postgres"
```

**"relation does not exist" errors** — The backend auto-detects fresh installs and creates tables. If you see this on an existing database, run migrations manually:
```bash
docker exec curatore-backend alembic upgrade head
```

**Frontend can't reach backend** — The frontend uses `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`). This is a browser-side URL, so it must be `localhost`, not `backend`.

**Worker not processing jobs** — Check worker health and logs:
```bash
docker ps --filter "name=curatore-worker"  # Should show (healthy)
./scripts/dev-logs.sh worker
```
