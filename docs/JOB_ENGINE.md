# Job Engine Architecture

Cross-cutting documentation for Curatore's job execution, tracking, and real-time update system.

## Overview

The job engine provides run-based execution tracking for all background work: document extraction, SharePoint syncs, SAM.gov pulls, web scrapes, Salesforce imports, forecast syncs, procedures, and maintenance tasks. Every background operation creates a **Run** record in PostgreSQL, executes via **Celery** workers, and pushes real-time updates to the frontend via **WebSocket**.

```
User Action → API creates Run → Celery task executes → WebSocket pushes updates → Frontend renders
```

## Architecture

### Backend

| Component | Location | Purpose |
|-----------|----------|---------|
| Run model | `app/core/database/models.py` | SQLAlchemy model with status, progress, config, group fields |
| RunGroup model | `app/core/database/models.py` | Groups parent + child runs (e.g., SharePoint sync + child extractions) |
| Run service | `app/core/shared/run_service.py` | CRUD operations, status transitions, progress updates |
| Run group service | `app/core/shared/run_group_service.py` | Create/manage run groups, link parent → children |
| Celery tasks | `app/core/tasks/*.py` | One module per job type (extraction, sharepoint, sam, scrape, etc.) |
| Queue registry | `app/core/ops/queue_registry.py` | Declares all queue types, timeouts, capabilities, Celery queue mapping |
| Priority queue | `app/core/ops/priority_queue_service.py` | Extraction queue with priority tiers and throttling |
| Job cancellation | `app/core/ops/job_cancellation_service.py` | Cancel individual runs or entire groups |
| Ops schemas | `app/api/v1/ops/schemas.py` | `RunResponse`, `RunWithLogsResponse`, queue stats |
| Ops routers | `app/api/v1/ops/routers/` | REST endpoints for runs, queue admin, stats |
| WebSocket | `app/api/v1/ops/routers/websocket.py` | Real-time job status/progress/log push |

### Frontend

| Component | Location | Purpose |
|-----------|----------|---------|
| Job type config | `lib/job-type-config.ts` | Registry of all job types: icons, colors, labels, resource links |
| Unified jobs context | `lib/unified-jobs-context.tsx` | WebSocket subscription, job state management, polling fallback |
| Job detail page | `app/system/jobs/[runId]/page.tsx` | Full job inspection: progress, logs, metadata, related resources |
| Jobs list page | `app/system/jobs/page.tsx` | System admin job queue browser |
| JobProgressPanel | `components/shared/JobProgressPanel.tsx` | Embeddable progress bar for resource pages |
| JobProgressPanelByType | `components/shared/JobProgressPanelByType.tsx` | Shows jobs filtered by type for a resource |
| Active jobs shim | `lib/context-shims.ts` | `useActiveJobs()` hook for tracking jobs from resource pages |

## Job Type Registry (`job-type-config.ts`)

The `JOB_TYPE_CONFIG` record is the single source of truth for job type metadata on the frontend. Each entry defines:

```typescript
interface JobTypeConfig {
  label: string             // Human-readable name ("SharePoint Sync")
  icon: LucideIcon          // Display icon
  color: string             // Tailwind color key (blue, purple, emerald, etc.)
  resourceType: string      // What resource this job operates on
  hasChildJobs: boolean     // Whether this type spawns child runs
  phases: string[]          // Expected progress phases
  completedToast: Function  // Toast message on completion
  failedToast: Function     // Toast message on failure
  getResourceLink?: Function // Returns a link to the related resource page
}
```

The `getJobTypeFromRunType()` function maps raw `run_type` strings (from the backend) to `JobType` keys, handling aliases like `extraction_enhancement` → `extraction`.

### Resource Links

Each job type can optionally define `getResourceLink(config, orgSlug)` which returns a `RelatedResource` object:

```typescript
interface RelatedResource {
  label: string     // "SharePoint Sync", "Parent Job", "Asset"
  name: string      // Human-readable name
  href: string      // Navigation target
  icon: LucideIcon
  color: string     // Tailwind color key
}
```

The `getRelatedResources()` function computes ALL links for a run by combining:
1. **Parent job link** — if `parent_run_id` is set
2. **Type-specific resource link** — from the registry's `getResourceLink`
3. **Asset links** — for extraction jobs with `input_asset_ids`

## Adding a New Job Type

### Backend

1. **Celery task**: Create in `app/core/tasks/<type>.py`, use `@celery_app.task(name="app.tasks.<module>.<task>")`
2. **Re-export**: Add to `app/core/tasks/__init__.py`
3. **Queue registry**: Add entry in `app/core/ops/queue_registry.py` with queue name, timeout, capabilities
4. **Run creation**: Task must create a Run record via `run_service.create_run()`
5. **Dispatch with tracking**: Use `run_service.submit_to_celery(session, run, task, kwargs, queue)` instead of bare `task.delay()`. This sets `celery_task_id`, `submitted_to_celery_at`, `last_activity_at`, and `status="submitted"` on the Run for proper monitoring and recovery.

### Frontend

5. **Job type config**: Add entry to `JOB_TYPE_CONFIG` in `lib/job-type-config.ts`
6. **Run type mapping**: Add to `directMap` in `getJobTypeFromRunType()` if the run_type differs from the job type key
7. **Resource link** (optional): Add `getResourceLink` to the config entry

The job detail page derives its display config (icon, label, color) from `JOB_TYPE_CONFIG` automatically via `getJobTypeFromRunType()` + `getJobTypeColorClasses()` — no page-local config to update.

## Job Detail Page

The job detail page (`/system/jobs/[runId]`) shows:

### Left Column (2/3 width)
- Error message (if failed)
- Progress bar with phase indicator
- Results summary (numeric stats, lists)
- Activity log timeline with expandable context

### Right Sidebar (1/3 width)
- **Timestamps**: Created, started, completed, duration, last activity
- **Related Resources**: Parent job, type-specific resource link, asset links (computed via `getRelatedResources()`)
- **Job Metadata**: Run type (human-readable label), origin, organization (linked), parent job (linked), queue, timeout, created by
- **Queue Capabilities**: Cancel, retry, throttled flags
- **Raw Data**: Expandable JSON viewers for config, progress, results

### Real-time Updates

The page subscribes to WebSocket updates via `useUnifiedJobs()`:
- Status changes update the status badge immediately
- Progress updates animate the progress bar
- New log events append to the timeline in real-time
- On terminal transition (completed/failed/cancelled), a final full fetch ensures complete data

Fallback: if WebSocket is disconnected, the page polls every 5 seconds for active jobs.

## WebSocket Integration

`unified-jobs-context.tsx` manages the WebSocket connection to `ws://localhost:8000/ws/jobs`:

1. **Connection lifecycle**: Auto-connect, reconnect with exponential backoff
2. **Job subscriptions**: Components register interest in specific run IDs
3. **State management**: Merges WebSocket updates into local job state
4. **Log streaming**: `subscribeToRunLogs(runId, callback)` for real-time log events
5. **Polling fallback**: When WebSocket is unavailable, falls back to periodic API polling

## JobProgressPanel

`JobProgressPanel` and `JobProgressPanelByType` are embeddable components that show job progress on resource pages (e.g., SharePoint config page shows sync progress). They use `useActiveJobs()` to find jobs matching a resource ID and display a compact progress indicator.

Usage from a resource page:
```tsx
import { JobProgressPanelByType } from '@/components/shared/JobProgressPanelByType'

<JobProgressPanelByType
  resourceId={configId}
  resourceType="sharepoint_config"
  jobType="sharepoint_sync"
/>
```
