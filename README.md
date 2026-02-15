# Curatore Local Development

Master repository for running the full Curatore platform locally. Each service lives in its own repository and is registered as a Git submodule.

## Architecture

```
curatore-localdev/
├── curatore-backend/           # FastAPI API + Celery workers + Redis + PostgreSQL
├── curatore-frontend/          # Next.js 15 web application
├── curatore-document-service/  # Document extraction microservice
├── curatore-playwright-service/# Browser rendering microservice
├── curatore-mcp-service/       # AI tool gateway (MCP protocol)
├── curatore-minio-service/     # S3-compatible object storage
└── scripts/                    # Orchestration scripts
```

All services communicate over a shared Docker network (`curatore-network`).

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
# Edit curatore-backend/.env with your API keys (at minimum: OPENAI_API_KEY)
```

### 3. Start everything

```bash
./scripts/dev-up.sh --with-postgres
```

This starts all services in dependency order:

1. Docker network (`curatore-network`)
2. MinIO (object storage)
3. Backend + Redis + PostgreSQL + Celery workers
4. Document Service
5. Playwright Service
6. Frontend
7. MCP Gateway

### 4. Seed the database (first time only)

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

## Scripts

| Script | Purpose |
|--------|---------|
| `./scripts/dev-up.sh` | Start all services |
| `./scripts/dev-up.sh --with-postgres` | Start with PostgreSQL |
| `./scripts/dev-up.sh --all` | Start with all optional services |
| `./scripts/dev-down.sh` | Stop all services |
| `./scripts/dev-logs.sh` | View backend logs |
| `./scripts/dev-logs.sh [service]` | View specific service logs |
| `./scripts/dev-status.sh` | Show running service status |

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
| MinIO Service | [curatore-minio-service](https://github.com/Amivero-LLC/curatore-minio-service) |

## Working with Submodules

```bash
# Pull latest changes for all submodules
git submodule update --remote

# Pull latest for a specific service
cd curatore-backend && git pull origin main

# After cloning on a new machine
git submodule update --init --recursive
```

## Stopping Services

```bash
# Stop everything
./scripts/dev-down.sh

# Remove the shared network (optional)
docker network rm curatore-network
```
