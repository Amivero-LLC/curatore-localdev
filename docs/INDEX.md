# Curatore Documentation Index

Master map of all documentation across Curatore repositories.

## Platform Architecture

| Document | Description |
|----------|-------------|
| [Platform Overview](OVERVIEW.md) | Service architecture, data flow, auth flows, CWR execution (Mermaid diagrams) |
| [Configuration](CONFIGURATION.md) | .env vs config.yml, config philosophy, service breakout pattern |
| [Document Processing](DOCUMENT_PROCESSING.md) | Upload → extraction → indexing pipeline |
| [Extraction Engines](EXTRACTION_SERVICES.md) | Triage, engine comparison, supported formats |
| [Data Connections](DATA_CONNECTIONS.md) | Adding new integrations (full checklist) |
| [Embedding Models & pgvector](EMBEDDING_MODELS.md) | Supported models, dimension auto-resolution, switching models in production |
| [Job Engine](JOB_ENGINE.md) | Run-based execution, Celery queues, WebSocket updates, job type registry |

## Backend

| Document | Description |
|----------|-------------|
| [Auth & Access Model](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/AUTH_ACCESS_MODEL.md) | Roles, org context, RBAC, dependency functions |
| [Search & Indexing](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/SEARCH_INDEXING.md) | pgvector, hybrid search, chunking, embeddings, reindexing |
| [Metadata Catalog](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/METADATA_CATALOG.md) | Namespaces, fields, facets, reference data, registry service |
| [Queue System](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/QUEUE_SYSTEM.md) | Celery queues, job groups, cancellation |
| [Functions & Procedures](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/FUNCTIONS_PROCEDURES.md) | CWR workflow automation, function reference |
| [API Documentation](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/API_DOCUMENTATION.md) | REST API reference (also at `/docs`) |
| [Maintenance Tasks](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/MAINTENANCE_TASKS.md) | Scheduled background tasks |

## Integrations

| Document | Description |
|----------|-------------|
| [SAM.gov](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/SAM_INTEGRATION.md) | Federal contracting opportunities |
| [Salesforce](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/SALESFORCE_INTEGRATION.md) | CRM data import |
| [SharePoint](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/SHAREPOINT_INTEGRATION.md) | Folder sync |
| [Forecasts](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/FORECAST_INTEGRATION.md) | Acquisition forecast sources |

## MCP Gateway

| Document | Description |
|----------|-------------|
| [MCP Service README](https://github.com/Amivero-LLC/curatore-mcp-service) | AI tool server overview |
| [Open WebUI Integration](https://github.com/Amivero-LLC/curatore-mcp-service/blob/main/docs/OPEN_WEBUI_INTEGRATION.md) | Setup walkthrough |

## Document Service

| Document | Description |
|----------|-------------|
| [Document Service README](https://github.com/Amivero-LLC/curatore-document-service) | Extraction and generation endpoints |

## Development

| Service | CLAUDE.md |
|---------|-----------|
| Localdev (this repo) | [CLAUDE.md](../CLAUDE.md) |
| Backend | [curatore-backend/CLAUDE.md](https://github.com/Amivero-LLC/curatore-backend/blob/main/CLAUDE.md) |
| Frontend | [curatore-frontend/CLAUDE.md](https://github.com/Amivero-LLC/curatore-frontend/blob/main/CLAUDE.md) |
| Document Service | [curatore-document-service/CLAUDE.md](https://github.com/Amivero-LLC/curatore-document-service/blob/main/CLAUDE.md) |
| MCP Service | [curatore-mcp-service/CLAUDE.md](https://github.com/Amivero-LLC/curatore-mcp-service/blob/main/CLAUDE.md) |
| Playwright Service | [curatore-playwright-service/CLAUDE.md](https://github.com/Amivero-LLC/curatore-playwright-service/blob/main/CLAUDE.md) |
