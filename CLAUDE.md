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
5. **Post-deploy data migrations** — When a schema migration needs follow-up operations that can't run in SQL (LLM calls, Playwright scraping, reindexing), use a flag-gated command in `app/core/commands/` wired into `prestart.py`. The `data_migrations` table tracks which commands have run — they execute once on first boot after deploy, then skip forever. See [backend CLAUDE.md](curatore-backend/CLAUDE.md) for the pattern.
6. **Four containers, one image** — Backend, worker-documents, worker-general, and beat all run from the same Docker image
7. **Service auth pattern** — All extracted services use optional `SERVICE_API_KEY`: empty = dev mode, set = validates `Authorization: Bearer <key>`
8. **Hot reload** — Python services mount `./app:/app/app` + `uvicorn --reload`; frontend mounts `.:/app` + `npm run dev`. No rebuild needed for source changes.
9. **Push-based health monitoring** — Three patterns, zero inter-service polling. See [Health Monitoring](docs/OVERVIEW.md#health-monitoring) for full details.
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

## Branching Strategy

All repositories follow the same branching model. `main` is the protected integration branch — all changes arrive via pull requests.

### Branch Types

| Branch Pattern | Purpose | Base | Merges Into | Example |
|---------------|---------|------|-------------|---------|
| `main` | Integration branch, always deployable | — | — | `main` |
| `feature/<slug>` | New features or enhancements | `main` | `main` via PR | `feature/sharepoint-sync` |
| `fix/<slug>` | Bug fixes | `main` | `main` via PR | `fix/jwt-refresh-race` |
| `chore/<slug>` | Maintenance, deps, config, CI | `main` | `main` via PR | `chore/upgrade-ruff` |
| `docs/<slug>` | Documentation-only changes | `main` | `main` via PR | `docs/api-auth-guide` |
| `release/<version>` | Release stabilization (when needed) | `main` | `main` via PR + tag | `release/1.0.0` |
| `hotfix/<slug>` | Urgent production fixes | `main` or `release/*` | `main` via PR | `hotfix/critical-auth-bypass` |

### Branch Naming Rules

- Use lowercase with hyphens: `feature/add-document-search` (not `feature/AddDocumentSearch`)
- Keep slugs short but descriptive (2-5 words)
- Include a ticket/issue number when one exists: `feature/42-sharepoint-sync`
- Never commit directly to `main` — always use a feature branch + PR

### Branch Lifecycle

```bash
# 1. Create feature branch from latest main
git checkout main && git pull
git checkout -b feature/my-change

# 2. Work, commit (see Commit Message Convention below)
git add <files> && git commit

# 3. Push and create PR
git push -u origin feature/my-change
gh pr create --base main

# 4. After PR merge, clean up
git checkout main && git pull
git branch -d feature/my-change
```

## Commit Message Convention

All repositories use **Conventional Commits** format for traceability and changelog generation.

### Format

```
<type>(<scope>): <short description>

[optional body — what and why, not how]

[optional footer(s)]
```

### Types

| Type | When to Use |
|------|------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code restructuring (no behavior change) |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `chore` | Maintenance, deps, config, CI |
| `perf` | Performance improvement |
| `style` | Formatting, linting (no logic change) |

### Scopes (optional, per service)

Use a short scope to indicate the area of change:

| Service | Common Scopes |
|---------|--------------|
| backend | `api`, `auth`, `workers`, `models`, `search`, `migrations`, `config`, `cwr` |
| frontend | `ui`, `api-client`, `auth`, `pages`, `components` |
| document-service | `extraction`, `generation`, `engines` |
| playwright-service | `rendering`, `config` |
| mcp-service | `tools`, `auth`, `middleware` |

### Examples

```
feat(api): add bulk document upload endpoint

Accepts multipart uploads of up to 50 files per request.
Validates file types against allowed_extensions config.

Closes #123
```

```
fix(auth): prevent JWT refresh race condition

Two concurrent 401s could trigger duplicate refresh requests.
Added mutex around the refresh token exchange.
```

```
chore(deps): upgrade FastAPI to 0.115.x
```

### Breaking Changes

Append `!` after the type/scope and add a `BREAKING CHANGE:` footer:

```
feat(api)!: rename /documents endpoint to /assets

BREAKING CHANGE: All clients must update from /api/v1/documents to /api/v1/assets.
Frontend and MCP service updated in companion PRs.

Cross-repo: frontend#87, mcp-service#34
```

### Localdev Submodule Reference Commits

When updating submodule pointers in localdev, use this format:

```
chore(submodules): update backend, frontend refs

backend: feat(api) - bulk document upload (#123)
frontend: feat(ui) - upload page redesign (#87)
```

## Pull Request Workflow

### PR Requirements (All Repos)

Every PR must satisfy these gates before merge:

1. **Branch is up to date with `main`** — rebase or merge main into your branch
2. **CI passes** — all three phases (lint, security, tests)
3. **PR description filled out** — use the template, link related issues/PRs
4. **Cross-repo PRs linked** — if changes span services, link companion PRs in the description
5. **No direct pushes to `main`** — all changes via PR

### PR Title Convention

PR titles should follow the same Conventional Commits format as commit messages:

```
feat(api): add bulk document upload endpoint
fix(auth): prevent JWT refresh race condition
chore(deps): upgrade FastAPI to 0.115.x
```

### Cross-Service PR Linking

When a change spans multiple repositories, link all related PRs:

```markdown
## Cross-Service PRs
- Backend: Amivero-LLC/curatore-backend#123
- Frontend: Amivero-LLC/curatore-frontend#87
- MCP: Amivero-LLC/curatore-mcp-service#34

Merge order: backend → mcp → frontend
```

## Cross-Service Feature Workflow

For changes that span multiple repositories (e.g., new API endpoint + frontend page + MCP tool):

### Coordination Pattern

1. **Plan the change** — identify which repos need changes and the merge order (usually: backend → extracted services → frontend)
2. **Use matching branch names** — create `feature/<slug>` in each affected repo with the same slug
3. **Backend first** — API contracts must be merged before consumers
4. **Link companion PRs** — each PR references the others in its description
5. **Update localdev last** — after all submodule PRs merge, update refs in localdev

### Step-by-Step

```bash
# 1. Create matching branches across repos
cd curatore-backend && git checkout -b feature/bulk-upload
cd ../curatore-frontend && git checkout -b feature/bulk-upload
cd ../curatore-mcp-service && git checkout -b feature/bulk-upload

# 2. Develop and test locally (all branches checked out)
./scripts/dev-up.sh --with-postgres
# ... make changes, run dev-check.sh ...

# 3. Push and create PRs in dependency order
cd curatore-backend && git push -u origin feature/bulk-upload
gh pr create --base main --title "feat(api): add bulk upload endpoint" --body "..."

cd ../curatore-mcp-service && git push -u origin feature/bulk-upload
gh pr create --base main --title "feat(tools): add bulk upload tool" --body "Cross-repo: backend#123"

cd ../curatore-frontend && git push -u origin feature/bulk-upload
gh pr create --base main --title "feat(ui): bulk upload page" --body "Cross-repo: backend#123, mcp#34"

# 4. Merge in order: backend → mcp → frontend
# 5. Update localdev submodule refs
cd ..
git checkout -b chore/bulk-upload-refs
git submodule update --remote curatore-backend curatore-mcp-service curatore-frontend
git add curatore-backend curatore-mcp-service curatore-frontend
git commit -m "chore(submodules): update refs for bulk upload feature

backend: feat(api) - bulk upload endpoint (#123)
mcp: feat(tools) - bulk upload tool (#34)
frontend: feat(ui) - bulk upload page (#87)"
git push -u origin chore/bulk-upload-refs
gh pr create --base main
```

### Merge Order Rules

| Change Type | Merge Order |
|------------|-------------|
| New API endpoint + frontend page | backend → frontend |
| New API + MCP tool + frontend | backend → mcp → frontend |
| Shared config change | backend → all consumers |
| Database migration + API change | backend (single PR: migration + API) |
| Frontend-only change | frontend only |
| Extraction engine change | document-service → backend (if API changed) |

## Submodule Workflow

```bash
# Create a feature branch in a submodule
cd curatore-backend
git checkout -b feature/my-change

# Work, commit with conventional format, push
git add <files>
git commit -m "feat(api): add new endpoint"
git push -u origin feature/my-change

# Create PR, get it reviewed and merged
gh pr create --base main

# After PR merges, update localdev submodule reference
cd ..
git checkout -b chore/update-backend-ref
git submodule update --remote curatore-backend
git add curatore-backend
git commit -m "chore(submodules): update backend ref

backend: feat(api) - add new endpoint (#42)"
git push -u origin chore/update-backend-ref
gh pr create --base main

# Pull all submodule updates (for other developers)
git submodule update --remote
```

## Agent Rules for Branching & Commits

These rules govern how AI agents (Claude Code, etc.) interact with git in this project.

### User Approval Required

Agents **must ask the user for confirmation** before:

| Action | Why |
|--------|-----|
| Creating a branch | User should agree on branch name and scope |
| Making a commit | User should review changes and approve the message |
| Pushing to a remote | Pushes are visible to the team |
| Creating a PR | PRs trigger notifications and CI |
| Merging or closing a PR | Irreversible team-visible action |
| Force-pushing or resetting | Destructive — could lose work |
| Deleting a branch | Could lose unmerged work |

### Pre-Commit Checklist (Agents)

Before creating any commit, agents must:

1. **Run quality checks** — `./scripts/dev-check.sh --service=<affected>` (or full sweep for cross-service changes)
2. **Verify all phases pass** — lint, security, tests. Fix failures before committing.
3. **Stage specific files** — use `git add <file1> <file2>`, not `git add -A` or `git add .`
4. **Use conventional commit format** — see [Commit Message Convention](#commit-message-convention)
5. **Show the user the diff and proposed message** — wait for approval before committing
6. **Never skip hooks** — no `--no-verify`, no `--no-gpg-sign`

### Post-Push Checklist (Agents)

After pushing, agents must:

1. **Verify CI passes** — `gh run list --repo Amivero-LLC/<repo> --limit 3`
2. **Report CI status to the user** — don't silently assume success
3. **If CI fails** — investigate logs with `gh run view <id> --log`, fix, and push again

### Branch Naming (Agents)

When an agent needs to create a branch:

1. Propose the branch name following the [Branch Types](#branch-types) convention
2. Include issue number if the user referenced one
3. Wait for user approval before creating

### Cross-Service Changes (Agents)

When a task requires changes across multiple repos:

1. **Plan first** — list all affected repos and the merge order
2. **Present the plan to the user** for approval before starting
3. **Use matching branch names** across repos
4. **Work in dependency order** — backend before consumers
5. **Link companion PRs** in each PR description
6. **Update localdev refs** after all submodule PRs merge

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
