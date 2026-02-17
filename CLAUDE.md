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
./scripts/dev-up.sh --with-docling     # Include Docling engine (CPU)
./scripts/dev-up.sh --with-docling-gpu # Include Docling engine (GPU)
./scripts/dev-down.sh                  # Stop everything
./scripts/dev-logs.sh                  # Backend logs
./scripts/dev-logs.sh worker           # All worker logs (fast + heavy + integrations)
./scripts/dev-logs.sh worker-fast      # Fast extraction worker logs
./scripts/dev-logs.sh worker-heavy     # Heavy extraction (Docling) worker logs
./scripts/dev-logs.sh worker-integrations # Integration sync worker logs
./scripts/dev-logs.sh docling          # Docling logs
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
                            │        └──── docling (:5001/:5151) │
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
| `docling` | `http://docling:5001` | Docling OCR/layout engine |
| `playwright` | `http://playwright:8011` | Rendering |
| `mcp` | `http://mcp:8020` | AI gateway |
| `frontend` | `http://frontend:3000` | Web UI |

## Cross-Service Development Rules

1. **API changes cascade** — When changing backend API endpoints, update: frontend `lib/api.ts`, MCP service contract converter, and docs
2. **Config split** — `.env` = secrets + Docker infrastructure; `config.yml` = application behavior + external service discovery. See [backend CLAUDE.md](curatore-backend/CLAUDE.md)
3. **Inter-service URLs** — Always use Docker container names (e.g., `http://document-service:8010`), never `localhost`. `localhost:PORT` is for browser/developer access only
4. **Migration parity** — When adding Alembic migrations that INSERT reference data or create VIEWs, also update `prestart.py` `_create_all_tables()` for fresh install parity
5. **Five containers, one image** — Backend, worker-fast, worker-heavy, worker-integrations, and beat all run from the same Docker image
6. **Service auth pattern** — All extracted services use optional `SERVICE_API_KEY`: empty = dev mode, set = validates `Authorization: Bearer <key>`
7. **Hot reload** — Python services mount `./app:/app/app` + `uvicorn --reload`; frontend mounts `.:/app` + `npm run dev`. No rebuild needed for source changes.

## Cross-Service Anti-Patterns

1. **NEVER** use `current_user.organization_id` directly — admin users have `NULL`. Use dependency functions.
2. **NEVER** hardcode LLM model names — always read from `config.yml`. No fallback defaults.
3. **NEVER** add silent config fallbacks — fail visibly with clear errors.
4. **NEVER** commit `.env` files — they contain secrets.
5. **NEVER** use `localhost` in inter-service Docker URLs.
6. **NEVER** assign users to `__system__` org — it's for CWR procedure ownership only.

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
| [Data Connections](docs/DATA_CONNECTIONS.md) | Adding new integrations |

## Quick Debugging

| Problem | Fix |
|---------|-----|
| `curatore-network not found` | `docker network create curatore-network` |
| Backend won't start (dependency timeout) | Check `docker ps --filter "name=curatore-"` for unhealthy containers |
| `relation does not exist` on existing DB | `docker exec curatore-backend alembic upgrade head` |
| Frontend can't reach backend | `NEXT_PUBLIC_API_URL` must be `http://localhost:8000` (browser-side URL) |
| Worker not processing jobs | Check `docker ps --filter "name=curatore-worker"` and `./scripts/dev-logs.sh worker`. Three pools: `worker-fast` (extraction/priority), `worker-heavy` (Docling), `worker-integrations` (syncs) |
| Docling not starting / unhealthy | CPU variant needs ~60s start_period for model loading; GPU needs ~120s. Check `./scripts/dev-logs.sh docling` and ensure `ENABLE_DOCLING_SERVICE=true` in root `.env` |
| Docling GPU fails | Ensure nvidia-docker runtime is installed and `ENABLE_DOCLING_GPU=true` in root `.env` |

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
