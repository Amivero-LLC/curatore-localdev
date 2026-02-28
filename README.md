# Curatore Local Development

Orchestration repo for running the full Curatore platform locally. Contains no application code — each service is a Git submodule.

## Prerequisites

- **Docker Desktop** (with Docker Compose v2)
- **Git** (with submodule support)
- **API Keys** — at minimum an LLM API key (OpenAI or LiteLLM proxy). SharePoint and SAM.gov keys are optional but enable full functionality.

## Quick Start

```bash
# 1. Clone with submodules
git clone --recurse-submodules https://github.com/Amivero-LLC/curatore-localdev.git
cd curatore-localdev

# 2. Run bootstrap (interactive — prompts for API keys, starts everything)
./scripts/bootstrap.sh
```

Bootstrap does everything automatically:

1. Initializes Git submodules
2. Creates `.env` from `.env.example` and prompts for required API keys
3. Auto-generates secrets (JWT key, service API keys, database passwords)
4. Distributes config to each service via `generate-env.sh`
5. Starts all Docker services

When it finishes, open **http://localhost:3000** — a setup wizard will guide you through creating your admin account.

### First-time setup

On a fresh install with no admin user, the frontend shows an interactive setup wizard at `/setup` where you create the initial administrator account. Once completed, this page is permanently inaccessible.

**Alternative (headless/CI):** You can also create the admin via CLI:
```bash
docker exec curatore-backend python -m app.core.commands.seed --create-admin
```

## Manual Setup

If you prefer step-by-step control:

```bash
# 1. Clone and init submodules
git clone --recurse-submodules https://github.com/Amivero-LLC/curatore-localdev.git
cd curatore-localdev

# 2. Create root .env and fill in your values (see "Environment Variables" below)
cp .env.example .env
# Edit .env with your API keys

# 3. Generate per-service configs from root .env
./scripts/generate-env.sh

# 4. Start all services
./scripts/dev-up.sh --with-postgres

# 5. Open http://localhost:3000 to create admin via setup wizard
# Or use CLI: docker exec curatore-backend python -m app.core.commands.seed --create-admin
```

## Architecture

```
curatore-localdev/
├── curatore-backend/           # FastAPI + Celery + Redis + PostgreSQL + MinIO + Chonkie
├── curatore-frontend/          # Next.js 15 + React 19 + Tailwind
├── curatore-document-service/  # Document extraction (PDF, DOCX, etc.)
├── curatore-playwright-service/# Browser rendering for web scraping
├── curatore-mcp-service/       # AI tool gateway (MCP protocol)
├── scripts/                    # Bootstrap, start/stop, config generation
└── docs/                       # Cross-cutting platform documentation
```

All services share a `curatore-network` Docker network and discover each other by container name.

### Service Map

| Service | Container | Local URL | Internal URL |
|---------|-----------|-----------|--------------|
| Frontend | `curatore-frontend` | http://localhost:3000 | http://frontend:3000 |
| Backend API | `curatore-backend` | http://localhost:8000 | http://backend:8000 |
| API Docs (Swagger) | — | http://localhost:8000/docs | — |
| Document Service | `curatore-document-service` | http://localhost:8010 | http://document-service:8010 |
| Playwright | `curatore-playwright` | http://localhost:8011 | http://playwright:8011 |
| MCP Gateway | `curatore-mcp` | http://localhost:8020 | http://mcp:8020 |
| MinIO Console | `curatore-minio` | http://localhost:9001 | minio:9000 |
| PostgreSQL | `curatore-postgres` | localhost:5432 | postgres:5432 |
| Redis | `curatore-redis` | localhost:6379 | redis:6379 |

**Local URLs** are for your browser. **Internal URLs** are how services talk to each other inside Docker.

### Port Map

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

## Environment Variables

All configuration starts in the **root `.env`** file. This is the single source of truth.

After editing `.env`, run `./scripts/generate-env.sh` to propagate changes to each service. See [`.env.example`](.env.example) for inline documentation on every variable.

### How Config Flows

```
 Root .env  ──→  generate-env.sh  ──→  curatore-backend/.env
                                  ──→  curatore-backend/config.yml
                                  ──→  curatore-frontend/.env
                                  ──→  curatore-document-service/.env
                                  ──→  curatore-playwright-service/.env
                                  ──→  curatore-mcp-service/.env
```

**Never edit per-service `.env` files directly** — they are regenerated from the root `.env`.

### Config Philosophy

| File | Purpose | Examples |
|------|---------|----------|
| **`.env`** | Secrets, credentials, infrastructure, dev toggles | API keys, DB passwords, `DEBUG`, `ENABLE_AUTH` |
| **`config.yml`** | Application behavior, LLM routing, search tuning | Model per task type, chunk sizes, queue settings |

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full reference.

### Required Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | LLM API key (OpenAI, LiteLLM proxy, or any OpenAI-compatible provider) |
| `OPENAI_BASE_URL` | LLM API endpoint URL |
| `OPENAI_MODEL` | Default model for all AI tasks (overridable per task type in `config.yml`) |

These enable full functionality but can be left blank to start without their features:

| Variable | Description |
|----------|-------------|
| `MS_TENANT_ID` | Azure AD tenant ID for SharePoint integration |
| `MS_CLIENT_ID` | Azure app registration client ID |
| `MS_CLIENT_SECRET` | Azure app registration client secret |
| `SAM_API_KEY` | SAM.gov API key for government opportunities (flows into `config.yml` `sam:` section via `generate-env.sh`) |

### Auto-Generated Secrets

Created by `bootstrap.sh` if left blank. Set manually for deterministic environments (CI, staging).

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | Signs authentication tokens. Changing it invalidates all sessions. |
| `MCP_API_KEY` | Shared secret between MCP gateway and backend. Also used as `TRUSTED_SERVICE_KEY` for delegated auth. |
| `DOCUMENT_SERVICE_API_KEY` | Authenticates backend requests to the document extraction service |
| `PLAYWRIGHT_API_KEY` | Authenticates backend requests to the browser rendering service |
| `MINIO_ROOT_USER` | MinIO admin username (default: `admin`) |
| `MINIO_ROOT_PASSWORD` | MinIO admin password |
| `POSTGRES_PASSWORD` | PostgreSQL password |

### Optional Overrides

Defaults work for local development. See [`.env.example`](.env.example) for full descriptions.

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `true` | Verbose logging across all services |
| `LOG_LEVEL` | `INFO` | Python log level (DEBUG, INFO, WARNING, ERROR) |
| `ENABLE_AUTH` | `true` | Set `false` to bypass JWT auth (local dev only) |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed browser origins (JSON array) |
| `ADMIN_EMAIL` | `admin@example.com` | CLI seed admin email (only used by `seed --create-admin`) |
| `ADMIN_PASSWORD` | `changeme` | CLI seed admin password (only used by `seed --create-admin`) |
| `ADMIN_USERNAME` | `admin` | CLI seed admin username (only used by `seed --create-admin`) |
| `ADMIN_FULL_NAME` | `Admin User` | CLI seed admin display name (only used by `seed --create-admin`) |
| `DEFAULT_ORG_NAME` | `Default Organization` | Default organization name |
| `DEFAULT_ORG_SLUG` | `default` | Default organization URL slug |
| `POSTGRES_DB` | `curatore` | PostgreSQL database name |
| `POSTGRES_USER` | `curatore` | PostgreSQL username |
| `ENABLE_POSTGRES_SERVICE` | `true` | Include local PostgreSQL container |
| `EMAIL_BACKEND` | `console` | `console` logs emails, `smtp` sends them |
| `EMAIL_FROM_ADDRESS` | `noreply@curatore.app` | Sender email address |
| `EMAIL_FROM_NAME` | `Curatore` | Sender display name |
| `SEARCH_ENABLED` | `true` | Enable hybrid full-text + semantic search |
### Docker-Only Variables (set automatically)

These are set by `generate-env.sh` or `docker-compose.yml` and don't need to be in the root `.env`:

| Variable | Value | Description |
|----------|-------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...@postgres:5432/curatore` | Derived from `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | Celery task broker (Redis DB 0) |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | Celery result store (Redis DB 1) |
| `TRUSTED_SERVICE_KEY` | Same as `MCP_API_KEY` | Delegated auth from MCP service |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO Docker container address |
| `MINIO_ACCESS_KEY` | Same as `MINIO_ROOT_USER` | MinIO access credential |
| `MINIO_SECRET_KEY` | Same as `MINIO_ROOT_PASSWORD` | MinIO secret credential |
| `DOCUMENT_SERVICE_URL` | `http://document-service:8010` | Docker container name |
| `PLAYWRIGHT_SERVICE_URL` | `http://playwright:8011` | Docker container name |
| `DOCUMENT_SERVICE_VERIFY_SSL` | `false` | No SSL between Docker containers |
## Scripts Reference

| Script | Purpose |
|--------|---------|
| `./scripts/bootstrap.sh` | One-command setup from fresh clone to running platform |
| `./scripts/bootstrap.sh --skip-start` | Configure only, don't start services |
| `./scripts/generate-env.sh` | Regenerate service configs after editing root `.env` |
| `./scripts/generate-env.sh --check` | Validate root `.env` has all required fields |
| `./scripts/dev-up.sh --with-postgres` | Start all services (includes local PostgreSQL) |
| `./scripts/dev-up.sh --all` | Start everything including optional services |
| `./scripts/dev-down.sh` | Stop all services |
| `./scripts/dev-logs.sh` | Backend logs |
| `./scripts/dev-logs.sh worker` | Celery worker logs |
| `./scripts/dev-logs.sh all` | All service logs |
| `./scripts/dev-status.sh` | Service health status |
| `./scripts/dev-check.sh` | Full quality check (lint + security + tests) |
| `./scripts/dev-check.sh --lint-only` | Linting only |
| `./scripts/dev-check.sh --test-only` | Tests only |
| `./scripts/dev-check.sh --security-only` | Security scanning only |
| `./scripts/dev-check.sh --service=backend` | Single service only |

## Common Tasks

### Run database migrations

```bash
docker exec curatore-backend alembic upgrade head
```

### Create a new migration

```bash
docker exec curatore-backend alembic revision --autogenerate -m "description"
```

### Create admin user (CLI alternative to setup wizard)

```bash
docker exec curatore-backend python -m app.core.commands.seed --create-admin
```

This only works when no admin user exists yet. After the first admin is created (via setup wizard or CLI), this command is a no-op.

### View worker queue health

```bash
docker exec curatore-worker celery -A app.celery_app inspect active
```

### Run quality checks

```bash
./scripts/dev-check.sh                       # Everything
./scripts/dev-check.sh --test-only           # Tests only
./scripts/dev-check.sh --service=backend     # Single service
```

### Health checks

```bash
# Liveness (zero I/O, always 200)
curl http://localhost:8000/api/v1/admin/system/health/live

# Readiness (checks DB + Redis + MinIO + startup complete)
curl http://localhost:8000/api/v1/admin/system/health/ready

# Comprehensive (all components)
curl http://localhost:8000/api/v1/admin/system/health/comprehensive
```

## Working with Submodules

```bash
# Pull latest changes for all submodules
git submodule update --remote

# Pull latest for a specific service
cd curatore-backend && git pull origin main

# After cloning on a new machine
git submodule update --init --recursive
```

When you make changes inside a submodule, commit in that submodule's repo first, then update the reference in localdev:

```bash
cd curatore-backend && git add -A && git commit -m "message" && git push
cd .. && git add curatore-backend && git commit -m "Update backend ref"
```

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

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `curatore-network not found` | `docker network create curatore-network` |
| Backend won't start | Check `docker ps --filter "name=curatore-"` for unhealthy containers |
| `relation does not exist` | `docker exec curatore-backend alembic upgrade head` |
| Frontend can't reach backend | `NEXT_PUBLIC_API_URL` must be `http://localhost:8000` (browser-side) |
| Worker not processing | `docker ps --filter "name=curatore-worker"` and `./scripts/dev-logs.sh worker` |
| Config out of sync after `.env` edit | `./scripts/generate-env.sh` to regenerate all service configs |

## Documentation

| Document | Description |
|----------|-------------|
| [Platform Overview](docs/OVERVIEW.md) | Architecture, data flow, auth flows |
| [Documentation Index](docs/INDEX.md) | Master map of all docs across all repos |
| [Configuration](docs/CONFIGURATION.md) | `.env` vs `config.yml` philosophy and full reference |
| [Document Processing](docs/DOCUMENT_PROCESSING.md) | Upload to extraction to indexing pipeline |
| [Extraction Engines](docs/EXTRACTION_SERVICES.md) | Triage and engine comparison |
| [Embedding Models & pgvector](docs/EMBEDDING_MODELS.md) | Supported models, dimension auto-resolution, switching models |
| [Data Connections](docs/DATA_CONNECTIONS.md) | Adding new integrations |

Each service also has its own `CLAUDE.md` with service-specific development guidance.

## Service Repositories

| Service | Repository |
|---------|-----------|
| Backend | [curatore-backend](https://github.com/Amivero-LLC/curatore-backend) |
| Frontend | [curatore-frontend](https://github.com/Amivero-LLC/curatore-frontend) |
| Document Service | [curatore-document-service](https://github.com/Amivero-LLC/curatore-document-service) |
| Playwright Service | [curatore-playwright-service](https://github.com/Amivero-LLC/curatore-playwright-service) |
| MCP Gateway | [curatore-mcp-service](https://github.com/Amivero-LLC/curatore-mcp-service) |
