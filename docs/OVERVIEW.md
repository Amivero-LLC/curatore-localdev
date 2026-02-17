# Curatore Platform Architecture

Curatore is a document processing and workflow automation platform for government acquisition teams. It ingests documents from multiple sources, extracts and indexes content, and provides LLM-powered search and analysis workflows.

## Services

```mermaid
graph TB
    subgraph External["External Access"]
        Browser["Browser :3000"]
        API["API Client :8000"]
        MCP_Client["MCP Client :8020"]
    end

    subgraph Platform["curatore-network"]
        Frontend["frontend\nNext.js 15\n:3000"]
        Backend["backend\nFastAPI\n:8000"]
        MCP["mcp\nMCP Gateway\n:8020"]
        WorkerFast["worker-fast\nCelery\n(extraction, priority, maintenance)"]
        WorkerHeavy["worker-heavy\nCelery\n(extraction_heavy / Docling)"]
        WorkerInt["worker-integrations\nCelery\n(SAM, SharePoint, scrape, forecast)"]
        Beat["beat\nCelery Beat"]

        DocService["document-service\nExtraction\n:8010"]
        Playwright["playwright\nBrowser Rendering\n:8011"]

        Postgres["postgres\nPostgreSQL + pgvector\n:5432"]
        Redis["redis\nBroker + Cache\n:6379"]
        MinIO["minio\nObject Storage\n:9000"]
    end

    Browser --> Frontend
    API --> Backend
    MCP_Client --> MCP

    Frontend --> Backend
    MCP --> Backend
    Backend --> Postgres
    Backend --> Redis
    Backend --> MinIO
    Backend --> DocService
    Backend --> Playwright

    WorkerFast --> Postgres
    WorkerFast --> Redis
    WorkerFast --> MinIO
    WorkerFast --> DocService
    WorkerHeavy --> Postgres
    WorkerHeavy --> Redis
    WorkerHeavy --> MinIO
    WorkerHeavy --> DocService
    WorkerInt --> Postgres
    WorkerInt --> Redis
    WorkerInt --> MinIO
    WorkerInt --> DocService
    Beat --> Redis

    DocService -.-> Docling["docling\nOCR + Layout\n:5001"]
```

### Service Responsibilities

| Service | Owns | Delegates To |
|---------|------|-------------|
| **backend** | API, auth, database schema, CWR runtime, search | document-service (extraction), playwright (rendering) |
| **worker-fast** | Fast extraction (PyMuPDF/MarkItDown), priority tasks, maintenance | document-service |
| **worker-heavy** | Complex extraction (Docling OCR/layout) | document-service → docling |
| **worker-integrations** | External API sync (SAM, SharePoint, Salesforce, scrape, forecast) | document-service, external APIs |
| **beat** | Cron scheduling (maintenance, reindex) | workers (via Redis) |
| **frontend** | UI, client-side routing | backend (API) |
| **mcp** | AI tool protocol, function exposure | backend (delegated auth + API) |
| **document-service** | Triage, extraction (fast_pdf, markitdown) | docling (complex OCR/layout) |
| **playwright** | Browser rendering, JS execution | — |

## Data Flow

```mermaid
flowchart LR
    subgraph Sources["Ingestion Sources"]
        Upload["Manual Upload"]
        SharePoint["SharePoint Sync"]
        SAM["SAM.gov Pull"]
        Scrape["Web Scrape"]
    end

    subgraph Processing["Processing Pipeline"]
        Asset["Asset Record\n(status=pending)"]
        MinIO_Up["MinIO\n(original bucket)"]
        DocSvc["Document Service\n(triage + extract)"]
        MinIO_Proc["MinIO\n(processed bucket)"]
        Indexer["Search Indexer\n(chunk + embed)"]
    end

    subgraph Storage["Searchable Storage"]
        PG["PostgreSQL\n(assets, extraction_results)"]
        PGV["pgvector\n(search_chunks)"]
    end

    Sources --> Asset
    Sources --> MinIO_Up
    MinIO_Up --> DocSvc
    DocSvc --> MinIO_Proc
    DocSvc --> PG
    MinIO_Proc --> Indexer
    Indexer --> PGV
    Asset --> PG
```

## Authentication

```mermaid
sequenceDiagram
    participant Browser
    participant Frontend
    participant Backend
    participant MCP as MCP Gateway

    Note over Browser,Backend: Path 1: JWT (Frontend Users)
    Browser->>Frontend: Login
    Frontend->>Backend: POST /auth/login
    Backend-->>Frontend: JWT token
    Frontend->>Backend: API requests (Bearer JWT)

    Note over Browser,Backend: Path 2: API Key (Programmatic)
    Browser->>Backend: X-API-Key header
    Backend-->>Browser: Response

    Note over MCP,Backend: Path 3: Delegated (MCP Gateway)
    MCP->>Backend: Service API key + user context
    Backend-->>MCP: Response (scoped to user's orgs)
```

### Auth Rules

- Admin users have `organization_id=NULL` — never use `current_user.organization_id` directly
- Non-admin users access orgs via `user_organization_memberships` (no primary org concept)
- System org (`__system__`) is for CWR procedure ownership only
- Use dependency functions: `get_effective_org_id`, `get_current_org_id`, `get_user_org_ids`, `require_admin`

## CWR (Workflow Runtime)

```mermaid
flowchart TD
    subgraph Functions["Functions (Atomic)"]
        Search["search_*\npayload: thin"]
        Get["get_content\npayload: full"]
        Generate["generate\nrequires: LLM"]
        Output["update_metadata\nside_effects: true"]
    end

    subgraph Procedures["Procedures (Multi-Step)"]
        Proc["Procedure Definition\n(YAML steps)"]
    end

    subgraph Pipelines["Pipelines (Chained)"]
        Pipe["Pipeline\n(procedure sequence)"]
    end

    subgraph Governance["Contract Governance"]
        Contract["FunctionMeta\n+ JSON Schema\n+ side_effects\n+ payload_profile\n+ exposure_profile"]
    end

    Search --> Proc
    Get --> Proc
    Generate --> Proc
    Output --> Proc
    Proc --> Pipe
    Contract -.- Functions
```

### CWR Execution Rules

1. **Functions** are atomic operations with governance metadata (`FunctionMeta`)
2. **Procedures** chain functions into multi-step workflows (YAML-defined)
3. **Pipelines** chain procedures for complex processing
4. **Contracts** are auto-derived from `FunctionMeta` — no manual contract files
5. The AI procedure generator uses governance fields to place functions correctly:
   - `payload_profile="thin"` search → insert `get_content` before LLM steps
   - `side_effects=True` functions placed late in workflows
   - `send_email`/`webhook` guarded with conditionals

## Related Documentation

- [Documentation Index](INDEX.md) — Master map of all docs across all repos
- [Configuration](CONFIGURATION.md) — .env vs config.yml philosophy
- [Document Processing](DOCUMENT_PROCESSING.md) — Upload → extraction → indexing
- [Extraction Engines](EXTRACTION_SERVICES.md) — Triage, engine comparison
- [Data Connections](DATA_CONNECTIONS.md) — Adding new integrations
