# Salesforce API Integration — Planning & Architecture

> **Status:** Planning (March 2026)
> **Scope:** Replace zip-import with API-based bidirectional sync
> **Repos:** curatore-backend, curatore-frontend, curatore-localdev

## Table of Contents

- [Overview](#overview)
- [Design Decisions](#design-decisions)
- [Architecture](#architecture)
- [Phase Plan](#phase-plan)
- [Data Model](#data-model)
- [Object Registry](#object-registry)
- [Authentication & Connection](#authentication--connection)
- [Sync Engine](#sync-engine)
- [Health Monitoring](#health-monitoring)
- [Search & Indexing](#search--indexing)
- [CWR Tools — Read](#cwr-tools--read)
- [CWR Tools — Write-Back](#cwr-tools--write-back)
- [Frontend](#frontend)
- [Configuration & Deployment](#configuration--deployment)
- [Testing Strategy](#testing-strategy)
- [Issue Tracker](#issue-tracker)
- [Open Questions & Future Work](#open-questions--future-work)

---

## Overview

Curatore currently imports Salesforce data via zip file upload (CSV export). This initiative replaces that with a live API integration using Salesforce's REST API and OAuth2 client_credentials flow.

### Goals

1. **One-way sync (Phase 1):** Pull Accounts, Contacts, and Opportunities from Salesforce via API with full and delta sync support
2. **Bidirectional sync (Phase 2):** Push updates back to Salesforce via CWR tools (update Opportunities and Contacts)
3. **Registry-driven design:** Adding new Salesforce objects (Contract, OpportunityContactRole) should be a config change + migration, not touching 6+ files
4. **Consistency:** Follow established patterns — SAM.gov sync, SharePoint sync, ExternalServiceMonitor, Run/RunGroup, queue registry

### What Changes

| Aspect | Before (Zip Import) | After (API Sync) |
|--------|---------------------|-------------------|
| Data ingestion | Manual zip upload of CSVs | Automated API sync (full + delta) |
| Frequency | Manual only | Manual, hourly, daily, weekly |
| Change detection | None (full replace) | SystemModstamp-based delta |
| Direction | One-way (import only) | Bidirectional (read + write-back) |
| Credentials | N/A | OAuth2 client_credentials, per-org Connection |
| Health monitoring | None | ExternalServiceMonitor + Redis heartbeat |
| Object extensibility | Hardcoded 3 types | Registry-driven (salesforce_objects.yaml) |
| Data model | FK-linked tables | Flat string references (salesforce_id) |

### What Stays the Same

- Three Salesforce tables: `salesforce_accounts`, `salesforce_contacts`, `salesforce_opportunities`
- Search indexing via `search_chunks` with pgvector embeddings
- Metadata builders and namespace fields
- CWR `search_salesforce` tool (enhanced, not replaced)
- Frontend browse pages for accounts, contacts, opportunities (enhanced)
- Existing zip import remains as deprecated fallback

---

## Design Decisions

### 1. Flat References Over Foreign Keys

**Decision:** Replace FK relationships between Salesforce tables with string `account_salesforce_id` references.

**Why:**
- Sync order independence — can sync Contacts before Accounts without FK violations
- Simpler upsert logic — no need to resolve Curatore UUIDs during sync
- Matches the Salesforce data model (Salesforce uses string IDs everywhere)
- Easier to add new objects without complex FK graphs

**Trade-off:** Join queries use string matching instead of UUID FKs. Mitigated by indexes on `account_salesforce_id`.

### 2. Registry-Driven Object Configuration

**Decision:** Create `salesforce_objects.yaml` as the single source of truth for which Salesforce objects we support, their field mappings, and indexing config.

**Why:**
- Currently, adding a new Salesforce object requires changes in 6+ files (import service, metadata builders, index service, search service, CWR tool, namespace YAML)
- With a registry, adding Contract or OpportunityContactRole becomes: add YAML entry + add model class + create migration
- Field mapping (Salesforce API name → Curatore column name) is centralized

### 3. ExternalServiceMonitor Pattern for Health

**Decision:** Use Tier 3 health monitoring (same as LLM and SharePoint) — event-driven with startup check and reactive recovery polling.

**Why:**
- Salesforce is an external API — periodic polling wastes API quota
- Consumer reporting (success/error from actual sync operations) is more accurate
- Recovery loop only activates when unhealthy — no wasted calls when healthy
- Consistent with existing patterns

### 4. Salesforce-Wins Conflict Resolution

**Decision:** When a record is modified in both Curatore and Salesforce between syncs, Salesforce's version wins.

**Why:**
- Simplest to implement correctly
- Salesforce is typically the system of record for CRM data
- Curatore stores the pending local change in `source_metadata.pending_changes` for audit
- Can evolve to configurable strategies later

### 5. Delta Sync with Safety Overlap

**Decision:** Delta syncs use a 5-minute overlap window (`SystemModstamp > last_sync_at - 5min`).

**Why:**
- Prevents edge cases where records modified during the exact sync window are missed
- Small overlap means minimal redundant processing (upsert is idempotent)
- Configurable via `config.yml` (`delta_overlap_minutes`)

---

## Architecture

### Data Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Salesforce REST API                           │
│                    (amivero.my.salesforce.com)                        │
└────────────┬────────────────────────────────────┬────────────────────┘
             │ OAuth2 client_credentials          │ PATCH/POST (write-back)
             ▼                                    ▲
┌────────────────────────┐              ┌─────────────────────┐
│  SalesforceApiClient   │              │  CWR Write-Back     │
│  (SOQL, pagination,    │              │  Tools               │
│   retry, rate limits)  │              │  (update/create)     │
└────────────┬───────────┘              └─────────┬───────────┘
             │                                    │
             ▼                                    │
┌────────────────────────┐                        │
│  SalesforceSyncService │                        │
│  (orchestrator)        │◄───────────────────────┘
│  - full sync           │
│  - delta sync          │
│  - upsert by sf_id     │
└────────────┬───────────┘
             │
     ┌───────┼────────┐
     ▼       ▼        ▼
┌────────┐┌────────┐┌────────┐
│Accounts││Contacts││  Opps  │   PostgreSQL tables
└───┬────┘└───┬────┘└───┬────┘
    │         │         │
    └─────────┼─────────┘
              ▼
┌────────────────────────┐
│  Batch Re-Index        │
│  (metadata builders    │
│   + embeddings)        │
└────────────┬───────────┘
             ▼
┌────────────────────────┐
│  search_chunks         │   pgvector + full-text
│  (unified search index)│
└────────────────────────┘
```

### Component Map

| Component | File Location | Pattern |
|-----------|--------------|---------|
| Object Registry | `app/metadata/registry/salesforce_objects.yaml` | New — YAML config |
| Adapter | `app/connectors/adapters/salesforce_adapter.py` | ServiceAdapter subclass |
| API Client | `app/connectors/salesforce/salesforce_api_client.py` | New — SOQL + REST |
| Sync Service | `app/connectors/salesforce/salesforce_sync_service.py` | Follows SAM pull_service pattern |
| Sync Config Model | `app/core/database/models.py` | SalesforceSyncConfig (new) |
| Celery Task | `app/core/tasks/salesforce.py` | Follows SAM task pattern |
| Scheduled Handler | `app/core/ops/maintenance_handlers.py` | Register new handler |
| Health Monitor | `app/core/shared/service_monitors.py` | ExternalServiceMonitor |
| Health Check | `app/api/v1/admin/routers/system.py` | `_check_salesforce()` |
| API Endpoints | `app/api/v1/connectors/routers/salesforce/` | Sync config CRUD + trigger |
| CWR Search | `app/cwr/tools/primitives/search/search_salesforce.py` | Existing, enhanced |
| CWR Write-Back | `app/cwr/tools/primitives/data/update_salesforce_record.py` | New |
| Metadata Builders | `app/core/search/metadata_builders.py` | Refactor to registry-driven |
| Frontend Pages | `app/orgs/[orgSlug]/syncs/salesforce/` | Replace zip UI |

---

## Phase Plan

### Phase 1: One-Way Sync (Salesforce → Curatore)

**Goal:** Replace zip import with automated API-based sync.

```
#71 Object Registry ──┐
#72 Adapter ───────────┼──→ #73 API Client ──→ #74 Sync Orchestrator
                       │                              │
#78 Health Monitor ────┘                              │
                                                      ▼
#76 Search Indexing ─────────────────────────→ #77 Config/Docs/Tests
                                                      │
Frontend #27 Sync Config UI ──→ #28 Browse Pages ──→ #29 Tests
```

**Deliverables:**
- Salesforce connection setup (per-org via UI or centralized via .env)
- Sync config creation (select objects, add filters, set frequency)
- Full and delta sync execution
- Search indexing with facets
- Health monitoring with Redis heartbeat
- Helm chart and config.yml updates

### Phase 2: Bidirectional Sync (Curatore → Salesforce)

**Goal:** CWR tools to update and create records in Salesforce.

```
#75 CWR Write-Back Tools
  ├── update_salesforce_record (Opportunities, Contacts)
  ├── create_salesforce_record (Opportunities, Contacts)
  └── Conflict detection during inbound sync
```

**Deliverables:**
- `update_salesforce_record` CWR primitive with dry-run
- `create_salesforce_record` CWR primitive with validation
- Conflict detection (Salesforce-wins)
- Sync status tracking per record (synced, pending_push, conflict)

### Phase 3: Extended Objects (Future)

- Contract and Contract_Vehicle__c tables
- OpportunityContactRole junction table
- Additional Salesforce standard objects as needed

### Phase 4: Content & Documents (Future)

- ContentDocument / ContentVersion sync
- Salesforce file attachments → Asset → extraction pipeline
- Linked to parent records (Opportunity, Account)

---

## Data Model

### Current State (FK-linked)

```
salesforce_accounts
    ├── salesforce_contacts (account_id FK → salesforce_accounts.id)
    └── salesforce_opportunities (account_id FK → salesforce_accounts.id)
```

### Target State (Flat references)

```
salesforce_accounts
    salesforce_id: String(18)    -- Salesforce 18-char ID
    sync_config_id: UUID         -- Which config synced this
    last_synced_at: DateTime     -- When last synced from SF
    sync_status: String(20)      -- "synced", "pending_push", "conflict"

salesforce_contacts
    salesforce_id: String(18)
    account_salesforce_id: String(18)  -- String ref, NOT FK
    sync_config_id, last_synced_at, sync_status

salesforce_opportunities
    salesforce_id: String(18)
    account_salesforce_id: String(18)  -- String ref, NOT FK
    sync_config_id, last_synced_at, sync_status

salesforce_sync_configs (NEW)
    id: UUID
    organization_id: UUID
    connection_id: UUID (nullable)
    name, slug, description
    sync_config: JSONB           -- {objects: [...], filters: {...}}
    sync_frequency: String       -- "manual", "hourly", "daily", "weekly"
    status: String               -- "active", "paused", "archived"
    last_sync_at, last_sync_status, last_sync_run_id
    last_full_sync_at
    stats: JSONB
    automation_config: JSONB     -- post-sync procedure triggers
```

### Migration Strategy

1. Add new columns (`account_salesforce_id`, `sync_config_id`, `last_synced_at`, `sync_status`)
2. Backfill `account_salesforce_id` from existing FK + joined salesforce_id
3. Create `salesforce_sync_configs` table
4. Keep old FK columns temporarily (mark deprecated)
5. Future migration removes deprecated FK columns after validation

---

## Object Registry

### `salesforce_objects.yaml`

Single source of truth for supported Salesforce objects:

```yaml
version: "1.0"
objects:
  Account:
    salesforce_api_name: Account
    curatore_source_type: salesforce_account
    curatore_table: salesforce_accounts
    display_name: Account
    syncable: true
    searchable: true
    default_soql_fields: [Id, Name, Type, Industry, ...]
    field_mapping:
      Id: salesforce_id
      Name: name
      Type: account_type
      # ... (see issue #71 for complete mapping)
    index_content_fields: [name, account_type, industry, description]
    facetable_fields: [account_type, industry]

  Contact:
    # ... similar structure

  Opportunity:
    # ... similar structure
```

### How It's Used

| Consumer | What It Reads |
|----------|--------------|
| SOQL builder | `default_soql_fields` → builds SELECT clause |
| Sync upsert | `field_mapping` → maps SF response → DB columns |
| Metadata builders | `index_content_fields` → composes searchable text |
| Facet definitions | `facetable_fields` → auto-generates facet config |
| CWR search tool | `searchable` objects → valid `entity_types` enum |
| CWR write-back | `field_mapping` (reverse) → maps DB columns → SF API names |
| Sync config UI | `syncable` objects → checkboxes in creation form |

### Adding a New Object

1. Add entry to `salesforce_objects.yaml`
2. Create model class in `models.py`
3. Create Alembic migration for table + indexes
4. Update `prestart.py` for fresh install parity
5. (Optional) Add namespace fields YAML in `fields/salesforce_{type}.yaml`

No changes needed in: metadata builders, index service, search service, CWR tools, API endpoints (all registry-driven).

---

## Authentication & Connection

### OAuth2 Flow

Salesforce Connected App with **client_credentials** grant:

```
POST https://{domain}/services/oauth2/token
  grant_type=client_credentials
  client_id={consumer_key}
  client_secret={consumer_secret}

Response:
  access_token: "00D..."
  instance_url: "https://amivero.my.salesforce.com"
  token_type: "Bearer"
  issued_at: "1773408960380"
```

- No refresh token — request new access token when needed
- Token cached in-memory with 55-minute TTL
- Proactive re-auth on 401 responses

### 3-Tier Config Resolution

| Priority | Source | Use Case |
|----------|--------|----------|
| 1 | DB `Connection` table | Per-org runtime config (via UI) |
| 2 | `config.yml` salesforce section | Deployment-level defaults |
| 3 | Environment variables | `.env` / Helm secrets |

### Credentials

```env
# .env
SALESFORCE_CONSUMER_KEY=3MVG99gP...
SALESFORCE_CONSUMER_SECRET=8C9654D...
SALESFORCE_DOMAIN=amivero.my.salesforce.com
```

### Connection Type Schema (UI Form)

```json
{
  "domain": { "type": "string", "pattern": "*.my.salesforce.com" },
  "consumer_key": { "type": "string", "writeOnly": true },
  "consumer_secret": { "type": "string", "writeOnly": true }
}
```

### Verified Connectivity

Confirmed working (March 2026) against `amivero.my.salesforce.com`:
- API version: v66.0
- Org: Amivero (Professional Edition, production)
- 645 SObjects accessible
- 10 Opportunities with full field access
- Test script: `scripts/salesforce/test_connectivity.py`

---

## Sync Engine

### Sync Config

Users create a `SalesforceSyncConfig` specifying:
- Which objects to sync (checkboxes: Account, Contact, Opportunity)
- Optional SOQL WHERE filters per object
- Sync frequency (manual / hourly / daily / weekly)
- Post-sync automation (procedure slug)

### Full vs. Delta Sync

| Mode | When | SOQL | Records |
|------|------|------|---------|
| Full | First sync, scheduled (weekly), user-triggered | `SELECT ... FROM {Object} ORDER BY SystemModstamp ASC` | All records |
| Delta | Subsequent syncs | `SELECT ... FROM {Object} WHERE SystemModstamp > {last_sync - 5min} ORDER BY SystemModstamp ASC` | Only changed records |

**Safety mechanisms:**
- 5-minute overlap window on delta queries (configurable)
- `last_full_sync_at` tracked separately — can force periodic full syncs
- User can always trigger manual full sync from UI
- Warning logged if delta returns 0 records 3 times consecutively

### Sync Lifecycle

```
User clicks "Sync Now"  ──or──  Scheduled handler fires
         │
         ▼
API: POST /sync-configs/{id}/sync
  ├── Create Run (status="pending")
  ├── Commit to DB
  └── Dispatch Celery task with run_id
         │
         ▼
Celery: salesforce_sync_task
  ├── Acquire distributed lock (sync:salesforce:{config_id})
  ├── Update Run → "running"
  ├── Create RunGroup for child operations
  ├── For each object type in config:
  │   ├── Build SOQL (full or delta)
  │   ├── Query Salesforce API (paginated via nextRecordsUrl)
  │   ├── Upsert records by salesforce_id (batch commit every 50)
  │   └── Track new/updated/unchanged counts
  ├── Batch re-index modified records in search_chunks
  ├── Update sync config (last_sync_at, stats)
  ├── Emit "salesforce_sync.completed" event
  ├── Trigger post-sync procedure (if configured)
  └── Release lock
```

### Queue

The `salesforce` queue is already registered in `queue_registry.py`:
- Queue type: `salesforce`
- Celery queue: `salesforce`
- Aliases: `salesforce_import` (to be updated to include `salesforce_sync`)
- Default timeout: 30 minutes
- Worker: `worker-general`

---

## Health Monitoring

### Pattern: ExternalServiceMonitor (Tier 3)

Same pattern as LLM and SharePoint — event-driven, not periodic polling.

```
                          startup_check()
                               │
                    ┌──────────▼──────────┐
                    │    NOT_CONFIGURED    │ (no credentials)
                    └─────────────────────┘
                               │ (credentials found)
                    ┌──────────▼──────────┐
              ┌────▶│      HEALTHY        │◀─── report_success()
              │     └──────────┬──────────┘
              │                │
              │     report_error() × threshold
              │                │
              │     ┌──────────▼──────────┐
              └─────│     UNHEALTHY       │──── recovery_loop (30s)
                    └─────────────────────┘
```

### Redis Heartbeat

- **Key:** `curatore:heartbeat:salesforce`
- **DB:** 2
- **Freshness threshold:** ~1 year (event-driven, not periodic)
- **Statuses:** `healthy`, `unhealthy`, `not_configured`

### Consumer Reporting

Every Salesforce API call in the client reports to the monitor:
- `salesforce_monitor.report_success()` / `report_success_sync()` on success
- `salesforce_monitor.report_error(str(e))` / `report_error_sync(str(e))` on failure

### System Status Impact

Salesforce is a **non-core** service — if unhealthy, overall system status becomes `degraded` (not `unhealthy`).

### Debugging

```bash
docker exec curatore-redis redis-cli -n 2 GET "curatore:heartbeat:salesforce"
curl http://localhost:8000/api/v1/admin/system/health/comprehensive?live=true
```

---

## Search & Indexing

### How Salesforce Records Are Searched

All Salesforce records are indexed into `search_chunks` (same table as SAM.gov, SharePoint, uploads):

```
SalesforceAccount → SalesforceAccountBuilder → search_chunks (source_type="salesforce_account")
SalesforceContact → SalesforceContactBuilder → search_chunks (source_type="salesforce_contact")
SalesforceOpportunity → SalesforceOpportunityBuilder → search_chunks (source_type="salesforce_opportunity")
```

### Content Composition

Builders compose searchable text from `index_content_fields` in the object registry:

- **Account:** `{name} {account_type} {industry} {description} {website}`
- **Contact:** `{first_name} {last_name} {title} {email} {department}`
- **Opportunity:** `{name} {description} {stage_name} {opportunity_type} {amount}`

### Facets

| Facet | Source Type | Metadata Path |
|-------|-----------|---------------|
| Opportunity Stage | salesforce_opportunity | salesforce_opportunity.stage_name |
| Industry | salesforce_account | salesforce_account.industry |
| Account Type | salesforce_account | salesforce_account.account_type |
| Amount Range | salesforce_opportunity | salesforce_opportunity.amount |
| Open/Closed | salesforce_opportunity | salesforce_opportunity.is_closed |

### Re-Indexing After Sync

Batch re-indexing triggered after sync completion:
1. Collect IDs of all created/updated records
2. Batch generate embeddings (single LLM API call per object type)
3. Upsert search_chunks
4. Update `indexed_at` on source records

---

## CWR Tools — Read

### `search_salesforce` (Existing, Enhanced)

```
Input:  query, entity_types, filters (stage, industry, amount, etc.)
Output: Ranked results with scores, source metadata, sync status
```

- Entity types driven by object registry (`searchable: true` objects)
- Hybrid search: keyword + semantic + optional reranking
- Filters applied via metadata JSONB containment queries
- Results include `sync_status` and `last_synced_at` for data freshness

---

## CWR Tools — Write-Back

### `update_salesforce_record` (Phase 2)

```
Input:  record_type, record_id, fields, dry_run
Output: Change summary (before/after values)
```

- Maps Curatore field names → Salesforce API names via object registry
- Validates read-only fields (Id, SystemModstamp)
- Dry-run mode shows diff without applying
- On success: updates local record, re-indexes, sets `sync_status="synced"`
- Audit trail via RunLog events

### `create_salesforce_record` (Phase 2)

```
Input:  record_type, fields, account_salesforce_id, dry_run
Output: New record details with salesforce_id
```

- Validates required fields per object type
- Creates in Salesforce first, then creates local record with returned ID
- Indexes in search_chunks

### Conflict Detection

During inbound sync, if a record has `sync_status="pending_push"` AND Salesforce's `SystemModstamp` is newer than our `last_synced_at`:
1. Log conflict warning
2. Store local pending changes in `source_metadata.pending_changes`
3. Overwrite with Salesforce version (Salesforce-wins)
4. Set `sync_status="conflict"` for manual review

---

## Frontend

### Pages

| Page | Purpose | Replaces |
|------|---------|----------|
| `/syncs/salesforce/` | Dashboard with sync stats | Zip upload page |
| `/syncs/salesforce/setup/` | Sync config list + creation | New |
| `/syncs/salesforce/[configId]/` | Config detail + history | New |
| `/syncs/salesforce/accounts/` | Browse synced accounts | Enhanced |
| `/syncs/salesforce/contacts/` | Browse synced contacts | Enhanced |
| `/syncs/salesforce/opportunities/` | Browse synced opportunities | Enhanced |

### Shared Components Reused

- `SyncTriggerButton` — "Sync Now" with loading state
- `SyncStatusBadge` — config + run status badges
- `LastSyncDisplay` — "Last sync: 2 hours ago"
- `SyncHistoryPanel` — paginated run history
- `SyncConfigTransfer` — import/export

### Sync Config Creation Flow

1. Name & description
2. Select connection (or use org default)
3. Select objects to sync (dynamic from backend registry)
4. Add filters per object (optional SOQL WHERE)
5. Set sync frequency
6. Preview (query Salesforce, show record counts + samples)
7. Confirm & save

### Record Browse Enhancements

- Sync status badges per record
- "View in Salesforce" deep links
- Data freshness indicators (green/yellow/red dots)
- Filter by sync config, sync status

---

## Configuration & Deployment

### .env Variables

```env
SALESFORCE_CONSUMER_KEY=       # Connected App Consumer Key
SALESFORCE_CONSUMER_SECRET=    # Connected App Consumer Secret
SALESFORCE_DOMAIN=             # e.g., amivero.my.salesforce.com
```

### config.yml Section

```yaml
salesforce:
  enabled: true
  domain: "${SALESFORCE_DOMAIN}"
  consumer_key: "${SALESFORCE_CONSUMER_KEY}"
  consumer_secret: "${SALESFORCE_CONSUMER_SECRET}"
  api_version: "v66.0"
  sync:
    default_page_size: 200
    rate_delay_seconds: 0.5
    delta_overlap_minutes: 5
    full_sync_interval_days: 7
```

### Helm Chart (`charts/values.yaml`)

Add to `configFiles` section — mirrors config.yml structure with empty defaults for secrets.

### generate-env.sh

Must propagate `SALESFORCE_*` variables into generated config.yml.

---

## Testing Strategy

### Unit Tests

| Area | What to Test |
|------|-------------|
| Object registry | YAML loading, field mapping validation |
| Adapter | 3-tier config resolution, token caching |
| API client | SOQL building, pagination, retry logic |
| Sync service | Full vs delta SOQL, upsert logic, batch indexing |
| CWR tools | Dry-run, field validation, conflict detection |
| Health check | Healthy, unhealthy, not_configured states |

### Smoke Tests

| Test | Verifies |
|------|---------|
| Full sync lifecycle | Config → trigger → records created → search indexed |
| Delta sync | Only fetches records modified since last sync |
| Sync with filters | SOQL WHERE applied correctly |
| API error mid-sync | Partial results saved, run marked failed |
| Distributed lock | Concurrent syncs rejected |
| Write-back dry run | Shows diff without calling SF API |
| Write-back apply | Calls SF API, updates local, re-indexes |
| Conflict detection | Dual modification detected, SF wins, logged |

### Frontend Tests

- Component tests for sync config form, record status badges
- Integration tests for config CRUD lifecycle
- API client method tests

### All Quality Gates

```bash
./scripts/dev-check.sh --service=backend    # Lint + security + tests
./scripts/dev-check.sh --service=frontend   # Lint + tests
gh run watch                                 # Verify CI after push
```

---

## Issue Tracker

### Backend (`curatore-backend`)

| Issue | Title | Phase | Dependencies |
|-------|-------|-------|-------------|
| [#71](https://github.com/Amivero-LLC/curatore-backend/issues/71) | Object registry and field mapping configuration | 1 | None |
| [#72](https://github.com/Amivero-LLC/curatore-backend/issues/72) | OAuth2 ServiceAdapter and Connection type | 1 | #71 |
| [#73](https://github.com/Amivero-LLC/curatore-backend/issues/73) | API client (SOQL, pagination, retry) | 1 | #71, #72 |
| [#74](https://github.com/Amivero-LLC/curatore-backend/issues/74) | Sync config model, endpoints, orchestrator | 1 | #71, #72, #73 |
| [#78](https://github.com/Amivero-LLC/curatore-backend/issues/78) | ExternalServiceMonitor + Redis heartbeat | 1 | #72, #73 |
| [#76](https://github.com/Amivero-LLC/curatore-backend/issues/76) | Search indexing, facets, metadata builders | 1 | #71, #74 |
| [#77](https://github.com/Amivero-LLC/curatore-backend/issues/77) | Config, deployment, docs, smoke tests | 1 | All Phase 1 |
| [#75](https://github.com/Amivero-LLC/curatore-backend/issues/75) | CWR write-back tools | 2 | All Phase 1 |

### Frontend (`curatore-frontend`)

| Issue | Title | Phase | Dependencies |
|-------|-------|-------|-------------|
| [#27](https://github.com/Amivero-LLC/curatore-frontend/issues/27) | Connection setup UI and sync config management | 1 | Backend #74 |
| [#28](https://github.com/Amivero-LLC/curatore-frontend/issues/28) | Record browse pages and detail views | 1 | Backend #74, Frontend #27 |
| [#29](https://github.com/Amivero-LLC/curatore-frontend/issues/29) | Component and integration tests | 1 | Frontend #27, #28 |

### Implementation Order

```
Phase 1 (One-way sync):
  Backend:  #71 → #72 → #73 → #74 + #78 → #76 → #77
  Frontend: #27 → #28 → #29 (can start after backend #74)

Phase 2 (Write-back):
  Backend:  #75 (after all Phase 1)
```

---

## Open Questions & Future Work

### Open Questions

1. **Batch write-back:** Should `update_salesforce_record` support updating multiple records in one call?
2. **Compound CWR tool:** Should `manage_salesforce_pipeline` (search + update workflow) be Phase 2 or Phase 3?
3. **Conflict UI:** Should users see conflicts in the browse page with a "Resolve" button, or just in logs?
4. **Custom fields:** How do we handle Salesforce custom fields (`__c` suffix) — auto-discover via `describe_object()` or manual YAML config?

### Future Work (Phase 3+)

- **Contract / Contract_Vehicle__c** — new object types via registry + migration
- **OpportunityContactRole** — junction table for contact-to-opportunity links
- **ContentDocument / ContentVersion** — file attachments through extraction pipeline
- **Salesforce Streaming API** — near real-time push notifications (replace polling)
- **Custom object support** — generic sync for any Salesforce object via `describe_object()` auto-discovery
- **Data validation rules** — enforce Salesforce validation rules locally before push

### Known Constraints

- Salesforce Professional Edition: 15,000 API calls/day
- Client credentials flow requires Connected App with "Enable Client Credentials Flow" checked
- No refresh tokens with client_credentials — must re-authenticate for each token
- Salesforce bulk API v2 may be needed for initial full syncs of large orgs (50K+ records)
